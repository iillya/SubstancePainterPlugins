cmake_minimum_required(VERSION 3.21)
project(sp_tools_delegate LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 同一份 sp_tools_delegate.cpp 编译两个 DLL：
#   * sp_layer_tools_delegate_qt5.dll - Painter 旧版（Qt 5.12.5）
#   * sp_layer_tools_delegate_qt6.dll - Painter 10.1+（Qt 6.x）
function(add_sp_tools_delegate target output_name qt_root qt_major)
    add_library(${target} SHARED sp_tools_delegate.cpp)
    target_include_directories(${target} PRIVATE
        "${qt_root}/include"
        "${qt_root}/include/QtCore"
        "${qt_root}/include/QtGui"
        "${qt_root}/include/QtWidgets"
        "${qt_root}/mkspecs/win32-msvc"
    )
    target_link_libraries(${target} PRIVATE
        "${qt_root}/lib/Qt${qt_major}Core.lib"
        "${qt_root}/lib/Qt${qt_major}Gui.lib"
        "${qt_root}/lib/Qt${qt_major}Widgets.lib"
    )
    target_compile_definitions(${target} PRIVATE
        QT_CORE_LIB QT_GUI_LIB QT_WIDGETS_LIB UNICODE _UNICODE)
    if(MSVC)
        target_compile_options(${target} PRIVATE
            /W4 /Zc:__cplusplus /permissive- /utf-8)
    endif()
    set_target_properties(${target} PROPERTIES
        OUTPUT_NAME "${output_name}"
        PREFIX ""
    )
endfunction()

set(QT6_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../sdks/qt/6.5.3/msvc2019_64")
if(NOT EXISTS "${QT6_ROOT}/lib/Qt6Widgets.lib")
    message(FATAL_ERROR "Bundled Qt6 SDK is missing")
endif()
add_sp_tools_delegate(
    sp_tools_delegate_qt6 sp_layer_tools_delegate_qt6 "${QT6_ROOT}" 6)

set(QT5_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../sdks/qt/5.12.5/msvc2017_64")
if(NOT EXISTS "${QT5_ROOT}/lib/Qt5Widgets.lib")
    message(FATAL_ERROR "Bundled Qt5.12.5 SDK is missing")
endif()
add_sp_tools_delegate(
    sp_tools_delegate_qt5 sp_layer_tools_delegate_qt5 "${QT5_ROOT}" 5)
