Подготовка пользователя и каталога

Если пользователя ещё нет:
sudo useradd --system --home /opt/dion-bot --shell /usr/sbin/nologin dionbot
Создай каталог:
sudo mkdir -p /opt/dion-bot
sudo chown -R dionbot:dionbot /opt/dion-bot

Разложить файлы бота
/opt/dion-bot/
├── bot.py
├── .env
└── venv/

Права:
sudo chown -R dionbot:dionbot /opt/dion-bot
sudo chmod 600 /opt/dion-bot/.env

Создать virtualenv и установить зависимости
cd /opt/dion-bot
python3 -m venv venv
source venv/bin/activate
pip install requests python-dotenv
deactivate

Если делаешь под пользователем dionbot:

sudo -u dionbot bash -lc '
cd /opt/dion-bot
python3 -m venv venv
source venv/bin/activate
pip install requests python-dotenv


файл .env

DION_EMAIL=bot@example.com
DION_PASSWORD=super-secret-password

# Настройки бота
DION_CAN_SEND_DM=true
DION_CAN_JOIN_GROUPS=true
DION_CAN_JOIN_CHANNELS=false

# Логи
LOG_LEVEL=INFO



Создать sudo nano /etc/systemd/system/dion-bot.service

[Unit]
Description=DION Chat Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dionbot
Group=dionbot
WorkingDirectory=/opt/dion-bot
EnvironmentFile=/opt/dion-bot/.env
ExecStart=/opt/dion-bot/venv/bin/python /opt/dion-bot/bot.py
Restart=always
RestartSec=5

# Без буферизации, чтобы логи сразу шли в journal
Environment=PYTHONUNBUFFERED=1

# Безопасность
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target


Перечитать systemd и включить сервис
sudo systemctl daemon-reload
sudo systemctl enable dion-bot
sudo systemctl start dion-bot