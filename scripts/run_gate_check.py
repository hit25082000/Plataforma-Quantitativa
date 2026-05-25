import asyncio
import json
import urllib.request
import websockets
import time

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000"

async def ws_keeper(path, stop_event):
    while not stop_event.is_set():
        try:
            async with websockets.connect(f"{WS_URL}{path}?symbol=WINFUT") as ws:
                print(f"[{path}] Connected")
                # Send a ping message so that server records "message" event in sessionops
                await ws.send(json.dumps({"event": "ping"}))
                print(f"[{path}] Sent ping")
                while not stop_event.is_set():
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"event": "ping"}))
        except Exception as e:
            if not stop_event.is_set():
                print(f"[{path}] Connection error: {e}. Retrying in 0.5s...")
                await asyncio.sleep(0.5)

async def publish_demo_loop(stop_event):
    url = f"{BASE_URL}/api/vp-overlay/demo"
    print(f"[Publisher] Publishing demo payload to {url}...")
    while not stop_event.is_set():
        try:
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=2.0)
        except Exception as e:
            print(f"[Publisher] Error: {e}")
        await asyncio.sleep(0.3)

def run_post(url, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))

async def main():
    # 1. Apply manual calibration
    calib_url = f"{BASE_URL}/api/ocr-overlay/manual-calibration"
    print(f"Calibrating OCR axis manually via {calib_url}...")
    calib_payload = {
        "points": [
            {"value": 100200.0, "y_screen": 100.0},
            {"value": 99800.0, "y_screen": 900.0}
        ]
    }
    try:
        res = run_post(calib_url, calib_payload)
        print("Manual calibration applied:", json.dumps(res, indent=2))
    except Exception as e:
        print(f"Calibration failed: {e}")

    # 2. Connect WS clients and start publishing demo data in background
    stop_event = asyncio.Event()
    ws1 = asyncio.create_task(ws_keeper("/ws/vp-overlay", stop_event))
    ws2 = asyncio.create_task(ws_keeper("/ws/volume-profile", stop_event))
    pub = asyncio.create_task(publish_demo_loop(stop_event))

    # Give some time for connections and initial posts to register
    print("Waiting 2 seconds for connections and updates to stabilize...")
    await asyncio.sleep(2.0)

    # 3. Call run-gate
    gate_url = f"{BASE_URL}/api/sessionops/run-gate"
    print(f"Calling run-gate at {gate_url}...")
    try:
        req = urllib.request.Request(gate_url, method="POST")
        resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=5.0)
        result = json.loads(resp.read().decode("utf-8"))
        print("Gate result:")
        print(json.dumps(result, indent=2))
        
        # Check agent-snapshot
        snap_url = f"{BASE_URL}/api/sessionops/agent-snapshot"
        req_snap = urllib.request.Request(snap_url, method="GET")
        resp_snap = await asyncio.to_thread(urllib.request.urlopen, req_snap, timeout=5.0)
        snap_result = json.loads(resp_snap.read().decode("utf-8"))
        print("Agent snapshot recommended next action:", snap_result.get("recommended_next_action"))
        
    except Exception as e:
        print(f"Error calling run-gate: {e}")
    finally:
        # 4. Clean up
        print("Stopping tasks...")
        stop_event.set()
        await asyncio.gather(ws1, ws2, pub, return_exceptions=True)
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
