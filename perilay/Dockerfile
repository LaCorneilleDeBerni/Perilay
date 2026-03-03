ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-pillow \
    bluez \
    bluez-libs \
    bluez-dev \
    python3-dev \
    musl-dev \
    gcc \
    ttf-dejavu \
    ttf-liberation \
    wget \
    git

# PyBluez depuis git master (compatible Python 3.12)
RUN pip3 install --break-system-packages \
    git+https://github.com/pybluez/pybluez.git#egg=PyBluez

# Librairie peripage + dépendances
RUN pip3 install --break-system-packages peripage==1.2 Pillow requests

# NotoEmoji v2.034 — format TTF classique compatible Pillow
RUN wget -q "https://github.com/googlefonts/noto-emoji/raw/v2.034/fonts/NotoEmoji-Regular.ttf" \
    -O /usr/share/fonts/NotoEmoji-Regular.ttf \
    && echo "Police emoji installée OK" \
    || echo "Téléchargement police emoji échoué (non bloquant)"

# Vérifier que les polices système sont bien installées
RUN test -f /usr/share/fonts/dejavu/DejaVuSans.ttf \
    || (echo "ERREUR: DejaVuSans.ttf absent" && exit 1)
RUN test -f /usr/share/fonts/liberation/LiberationSans-Regular.ttf \
    || (echo "ERREUR: LiberationSans-Regular.ttf absent" && exit 1)

# Nettoyer les outils de build pour réduire la taille de l'image
RUN apk del bluez-dev python3-dev musl-dev gcc git \
    && rm -rf /root/.cache /tmp/*

COPY run.sh /
COPY layout_service.py /

RUN chmod +x /run.sh

CMD ["/run.sh"]
