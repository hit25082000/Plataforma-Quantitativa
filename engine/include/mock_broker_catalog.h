#pragma once

#include <cstddef>
#include <cstdint>

struct MockBrokerCatalogEntry {
    int32_t id;
    const char* sigla;
};

/** Catálogo fixo para o simulador TESTE/SIM: ids estáveis + siglas reais de mesa. Se o Profit do seu ambiente usar outros códigos para as mesas, ajuste os ids. */
inline constexpr MockBrokerCatalogEntry k_mock_broker_catalog[] = {
    {30, "UBS"},
    {40, "BTG"},
    {77, "GOLDM"},
    {85, "XP"},
    {3, "ITAU"},
    {120, "CS"},
    {15, "MS"},
    {22, "CITI"},
    {9, "BARCL"},
    {118, "JPM"},
};

inline constexpr size_t k_mock_broker_catalog_count =
    sizeof(k_mock_broker_catalog) / sizeof(k_mock_broker_catalog[0]);

inline const char* mock_broker_sigla_for_id(int32_t id) {
    for (size_t i = 0; i < k_mock_broker_catalog_count; ++i) {
        if (k_mock_broker_catalog[i].id == id) return k_mock_broker_catalog[i].sigla;
    }
    return nullptr;
}

inline int32_t mock_broker_id_at(size_t index) {
    return k_mock_broker_catalog[index % k_mock_broker_catalog_count].id;
}
