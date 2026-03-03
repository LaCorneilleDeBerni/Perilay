#!/usr/bin/with-contenv bashio

MAC=$(bashio::config 'printer_mac')
MODEL=$(bashio::config 'printer_model')
FONT=$(bashio::config 'font')
FONT_SIZE=$(bashio::config 'font_size')
PORT=$(bashio::config 'port')
CUSTOM_FONTS=$(bashio::config 'custom_fonts' || echo '[]')

bashio::log.info "PeriPage Layout — démarrage"
bashio::log.info "MAC: ${MAC} | Modèle: ${MODEL} | Port: ${PORT}"

trap 'bashio::log.info "Arrêt."; kill ${PID}; exit 0' SIGTERM SIGINT

python3 /layout_service.py "${MAC}" "${MODEL}" "${FONT}" "${FONT_SIZE}" "${PORT}" "${CUSTOM_FONTS}" &
PID=$!
wait ${PID}
