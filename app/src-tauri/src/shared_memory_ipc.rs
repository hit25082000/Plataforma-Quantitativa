use serde_json::json;
use std::mem::size_of;
use std::ptr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter};

#[cfg(target_os = "windows")]
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
#[cfg(target_os = "windows")]
use windows_sys::Win32::System::Memory::{
    FILE_MAP_READ, MEMORY_MAPPED_VIEW_ADDRESS, MapViewOfFile, OpenFileMappingA, UnmapViewOfFile,
};

const SHM_MAGIC: u32 = 0x504D4853;
const SHM_VERSION: u32 = 1;
const MESSAGE_TYPE_TRADE: u32 = 1;

const EVENT_MARKET: &str = "pq:market-message";
const EVENT_IPC_FALLBACK: &str = "pq:ipc-fallback";
const EVENT_IPC_TRANSPORT: &str = "pq:ipc-transport";

static STARTED: OnceLock<AtomicBool> = OnceLock::new();

#[repr(C)]
#[derive(Clone, Copy)]
struct TradePayload {
    ticker: [u8; 24],
    trade_date: [u8; 16],
    price: f64,
    qty: i64,
    buy_agent: i32,
    sell_agent: i32,
    trade_type: u8,
    trade_source: u8,
    reserved0: u16,
    trade_number: u32,
    trade_flags: u32,
    trade_epoch_ms: i64,
    vwap: f64,
    net_aggression: i64,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct RingHeader {
    magic: u32,
    version: u32,
    header_size: u32,
    slot_size: u32,
    capacity: u64,
    write_seq: u64,
    dropped: u64,
    created_epoch_ms: u64,
    reserved: [u64; 8],
}

#[repr(C)]
#[derive(Clone, Copy)]
struct RingSlot {
    committed_seq: u64,
    message_type: u32,
    payload_size: u32,
    trade: TradePayload,
}

struct MappedView {
    handle: HANDLE,
    view: MEMORY_MAPPED_VIEW_ADDRESS,
    ptr: *const u8,
}

impl Drop for MappedView {
    fn drop(&mut self) {
        #[cfg(target_os = "windows")]
        unsafe {
            if !self.ptr.is_null() {
                let _ = UnmapViewOfFile(self.view);
            }
            if !self.handle.is_null() {
                let _ = CloseHandle(self.handle);
            }
        }
    }
}

fn cstr(bytes: &[u8]) -> String {
    let end = bytes.iter().position(|b| *b == 0).unwrap_or(bytes.len());
    String::from_utf8_lossy(&bytes[..end]).to_string()
}

fn iso_ts(epoch_ms: i64) -> String {
    if epoch_ms <= 0 {
        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        return format!("{now_ms}");
    }
    format!("{epoch_ms}")
}

#[cfg(target_os = "windows")]
fn open_mapping(mapping_name: &str) -> Result<MappedView, String> {
    let name = format!("{mapping_name}\0");
    let handle = unsafe { OpenFileMappingA(FILE_MAP_READ, 0, name.as_ptr()) };
    if handle.is_null() {
        return Err("mapping_not_found".to_string());
    }
    let view = unsafe { MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0) };
    if view.Value.is_null() {
        unsafe {
            let _ = CloseHandle(handle);
        }
        return Err("map_view_failed".to_string());
    }
    Ok(MappedView {
        handle,
        view,
        ptr: view.Value as *const u8,
    })
}

#[cfg(not(target_os = "windows"))]
fn open_mapping(_mapping_name: &str) -> Result<MappedView, String> {
    Err("unsupported_os".to_string())
}

fn read_header(ptr_base: *const u8) -> RingHeader {
    unsafe { ptr::read_unaligned(ptr_base as *const RingHeader) }
}

fn read_slot(ptr_base: *const u8, header: &RingHeader, idx: usize) -> RingSlot {
    let slot_size = header.slot_size as usize;
    let start = size_of::<RingHeader>() + idx * slot_size;
    unsafe { ptr::read_unaligned(ptr_base.add(start) as *const RingSlot) }
}

fn crc16_ccitt(data: &[u8], init: u16) -> u16 {
    let mut crc = init;
    for byte in data {
        crc ^= (*byte as u16) << 8;
        for _ in 0..8 {
            if (crc & 0x8000) != 0 {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    crc
}

fn slot_crc16(slot: &RingSlot) -> u16 {
    let mut trade = slot.trade;
    trade.reserved0 = 0;
    let mut crc = crc16_ccitt(&slot.message_type.to_le_bytes(), 0xFFFF);
    crc = crc16_ccitt(&slot.payload_size.to_le_bytes(), crc);
    let trade_bytes = unsafe {
        std::slice::from_raw_parts((&trade as *const TradePayload).cast::<u8>(), size_of::<TradePayload>())
    };
    crc16_ccitt(trade_bytes, crc)
}

fn emit_fallback(app: &AppHandle, reason: &str, mapping_name: &str) {
    let payload = json!({
        "topic": "system",
        "type": "ipc_fallback",
        "requested_mode": "shm",
        "effective_mode": "websocket",
        "reason": reason,
        "mapping_name": mapping_name,
    });
    let _ = app.emit(EVENT_IPC_FALLBACK, payload.clone());
    let _ = app.emit(EVENT_IPC_TRANSPORT, json!({"mode":"websocket","reason": reason}));
}

pub fn start_reader(app: AppHandle) {
    let started = STARTED.get_or_init(|| AtomicBool::new(false));
    if started.swap(true, Ordering::SeqCst) {
        return;
    }

    thread::spawn(move || {
        let mapping_name =
            std::env::var("SHM_MAPPING_NAME").unwrap_or_else(|_| "Local\\PQMarketDataV1".to_string());
        let view = match open_mapping(&mapping_name) {
            Ok(v) => v,
            Err(reason) => {
                emit_fallback(&app, &reason, &mapping_name);
                return;
            }
        };

        let header = read_header(view.ptr);
        if header.magic != SHM_MAGIC || header.version != SHM_VERSION || header.capacity == 0 {
            emit_fallback(&app, "invalid_header", &mapping_name);
            return;
        }

        let _ = app.emit(EVENT_IPC_TRANSPORT, json!({"mode":"shm","reason":"ok"}));
        let mut next_seq: u64 = 1;
        let mut integrity_failures: u64 = 0;

        loop {
            let header_live = read_header(view.ptr);
            let write_seq = header_live.write_seq;
            let capacity = header_live.capacity;
            if write_seq == 0 || capacity == 0 {
                thread::sleep(Duration::from_micros(500));
                continue;
            }

            let min_seq = write_seq.saturating_sub(capacity).saturating_add(1);
            if next_seq < min_seq {
                next_seq = min_seq;
            }
            if next_seq > write_seq {
                thread::sleep(Duration::from_micros(500));
                continue;
            }

            let idx = ((next_seq - 1) % capacity) as usize;
            let slot = read_slot(view.ptr, &header_live, idx);
            if slot.committed_seq != next_seq {
                if slot.committed_seq > next_seq {
                    next_seq = slot.committed_seq;
                } else {
                    thread::sleep(Duration::from_micros(500));
                }
                continue;
            }
            if slot.message_type != MESSAGE_TYPE_TRADE {
                next_seq += 1;
                continue;
            }
            if slot.payload_size as usize != size_of::<TradePayload>() {
                integrity_failures += 1;
                if (integrity_failures % 500) == 1 {
                    eprintln!("[SHM][Tauri] integrity_failures={} reason=payload_size", integrity_failures);
                }
                next_seq += 1;
                continue;
            }
            let expected_crc = slot.trade.reserved0;
            let got_crc = slot_crc16(&slot);
            if got_crc != expected_crc {
                integrity_failures += 1;
                if (integrity_failures % 500) == 1 {
                    eprintln!(
                        "[SHM][Tauri] integrity_failures={} reason=crc_mismatch expected={} got={}",
                        integrity_failures, expected_crc, got_crc
                    );
                }
                next_seq += 1;
                continue;
            }

            let trade = slot.trade;
            let payload = json!({
                "topic": "market",
                "type": "trade",
                "ticker": cstr(&trade.ticker),
                "price": trade.price,
                "qty": trade.qty,
                "buy_agent": trade.buy_agent,
                "sell_agent": trade.sell_agent,
                "trade_type": trade.trade_type,
                "trade_number": trade.trade_number,
                "trade_date": cstr(&trade.trade_date),
                "trade_source": if trade.trade_source == 1 { "history" } else { "realtime" },
                "is_edit": (trade.trade_flags & 0x1) != 0,
                "vwap": trade.vwap,
                "net_aggression": trade.net_aggression,
                "ts": iso_ts(trade.trade_epoch_ms),
            });
            let _ = app.emit(EVENT_MARKET, payload);
            next_seq += 1;
        }
    });
}
