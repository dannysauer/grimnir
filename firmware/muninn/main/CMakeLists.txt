idf_component_register(
    SRCS "main.c" "syslog_client.c"
    INCLUDE_DIRS "." "../.."
    REQUIRES esp_wifi nvs_flash lwip esp_timer
)

target_link_libraries(${COMPONENT_LIB} PRIVATE m)
