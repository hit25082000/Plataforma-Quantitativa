cmake_minimum_required(VERSION 3.25)
project(plataforma-quantitativa-engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

# vcpkg
if(DEFINED ENV{VCPKG_ROOT})
  set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
      CACHE STRING "Vcpkg toolchain file")
endif()

# Sources
set(ENGINE_SOURCES
  src/main.cpp
  src/asset_controller.cpp
  src/mock_feed.cpp
  src/profit_bridge.cpp
  src/event_bus.cpp
  src/alert_bus.cpp
  src/dom_snapshot.cpp
  src/trade_stream.cpp
  src/event_dispatcher.cpp
  src/zmq_publisher.cpp
  src/rules/rule1_aggression.cpp
  src/rules/rule2_wall.cpp
  src/rules/rule3_vwap.cpp
  src/rules/rule5_convergence.cpp
  src/rules/rule6_absorption.cpp
)

# Find vcpkg packages
find_package(nlohmann_json CONFIG REQUIRED)
find_package(cppzmq CONFIG REQUIRED)

# Executable
add_executable(engine ${ENGINE_SOURCES})

target_include_directories(engine PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(engine PRIVATE
  nlohmann_json::nlohmann_json
  cppzmq
  libzmq
)

# Copy DLL to output: manual requires ProfitDLL64.dll for 64-bit, ProfitDLL.dll for 32-bit
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  set(PROFIT_DLL_NAME "ProfitDLL64.dll")
else()
  set(PROFIT_DLL_NAME "ProfitDLL.dll")
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../${PROFIT_DLL_NAME}")
  add_custom_command(TARGET engine POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      "${CMAKE_CURRENT_SOURCE_DIR}/../${PROFIT_DLL_NAME}"
      $<TARGET_FILE_DIR:engine>
    COMMENT "Copying ${PROFIT_DLL_NAME} to output directory"
  )
else()
  message(STATUS "${PROFIT_DLL_NAME} not found at repo root; skipping post-build copy (run-dev.ps1 handles it)")
endif()
