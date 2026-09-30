import os
import json
import time
import uuid
import logging
import hashlib
import threading
import urllib.request
import urllib.parse
import psycopg2

# ------------------------------------------------------------------------------
# 1. КОНФИГУРАЦИЯ И ВЕРСИОНИРОВАНИЕ
# ------------------------------------------------------------------------------
CPA_DISTRIBUTION_ENGINE_VERSION = "2.3"
os.environ["CPA_DISTRIBUTION_ENGINE_VERSION"] = CPA_DISTRIBUTION_ENGINE_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cpafactory")

# ------------------------------------------------------------------------------
# 2. АВТОМАТИЧЕСКАЯ ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ------------------------------------------------------------------------------
def init_db(db_url):
    if not db_url:
        logger.warning("DATABASE_URL missing. DB auto-init skipped.")
        return

    schema_sql = """
    CREATE TABLE IF NOT EXISTS system_state (
        key VARCHAR(64) PRIMARY KEY,
        value_text TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS offers (
        id SERIAL PRIMARY KEY,
        external_id VARCHAR(128) NOT NULL UNIQUE,
        source VARCHAR(64) NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        image_url TEXT,
        original_url TEXT NOT NULL,
        affiliate_url TEXT NOT NULL,
        commission_value NUMERIC(10, 2) DEFAULT 0.0,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS materials (
        id SERIAL PRIMARY KEY,
        offer_id INT REFERENCES offers(id) ON DELETE CASCADE,
        title VARCHAR(255) NOT NULL,
        content_text TEXT NOT NULL,
        status VARCHAR(32) DEFAULT 'ready',
        idempotency_key VARCHAR(128) UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS publications (
        id SERIAL PRIMARY KEY,
        material_id INT REFERENCES materials(id) ON DELETE CASCADE,
        channel VARCHAR(64) NOT NULL,
        external_publication_id VARCHAR(128) NOT NULL,
        published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS clicks (
        click_id VARCHAR(64) PRIMARY KEY,
        offer_id INT REFERENCES offers(id) ON DELETE CASCADE,
        publication_id INT REFERENCES publications(id) ON DELETE CASCADE,
        user_agent TEXT,
        ip_address VARCHAR(45),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cursor:
            cursor.execute(schema_sql)
        conn.commit()
        conn.close()
        logger.info("CPA_DB_INITIALIZED | Schema updated successfully.")
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")

# ------------------------------------------------------------------------------
# 3. TELEGRAM PUBLISHER
# ------------------------------------------------------------------------------
def publish_to_telegram(bot_token, channel_id, text, image_url=None):
    base_url = f"https://api.telegram.org/bot{bot_token}"
    
    if image_url:
        try:
            data = urllib.parse.urlencode({
                "chat_id": channel_id,
                "caption": text,
                "parse_mode": "HTML",
                "photo": image_url
            }).encode('utf-8')
            req = urllib.request.Request(f"{base_url}/sendPhoto", data=data)
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get("ok"):
                    return True, str(res["result"]["message_id"])
        except Exception:
            pass

    try:
        data = urllib.parse.urlencode({
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "HTML"
        }).encode('utf-8')
        req = urllib.request.Request(f"{base_url}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            if res.get("ok"):
                return True, str(res["result"]["message_id"])
            return False, res.get("description", "Publish error")
    except Exception as e:
        return False, str(e)

# ------------------------------------------------------------------------------
# 4. ФОНОВЫЙ АВТОПИЛОТ
# ------------------------------------------------------------------------------
def autopilot_loop():
    db_url = os.getenv("DATABASE_URL")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "@CPAFactory")
    app_base_url = os.getenv("APP_BASE_URL", "https://cpafactory-web.onrender.com")

    if not db_url or not bot_token:
        logger.warning("CPA_AUTOPILOT | Missing DATABASE_URL or TELEGRAM_BOT_TOKEN")
        return

    LOCK_ID = 883920192
    
    while True:
        try:
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s);", (LOCK_ID,))
            locked = cursor.fetchone()[0]

            if locked:
                logger.info("CPA_AUTOPILOT | Lock acquired. Checking active offers...")
                cursor.execute("""
                    SELECT o.id, o.title, o.description, o.image_url 
                    FROM offers o WHERE o.is_active = TRUE ORDER BY o.id DESC LIMIT 1;
                """)
                offer = cursor.fetchone()

                if offer:
                    offer_id, title, desc, image_url = offer
                    raw_key = f"{offer_id}_telegram_{title}"
                    idempotency_key = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

                    cursor.execute("SELECT id FROM materials WHERE idempotency_key = %s;", (idempotency_key,))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO materials (offer_id, title, content_text, status, idempotency_key)
                            VALUES (%s, %s, %s, 'processing', %s) RETURNING id;
                        """, (offer_id, title, desc, idempotency_key))
                        material_id = cursor.fetchone()[0]
                        conn.commit()

                        click_id = str(uuid.uuid4())
                        tracking_link = f"{app_base_url.rstrip('/')}/r/{click_id}?off={offer_id}&pub={material_id}"
                        
                        post_text = (
                            f"🔥 <b>{title}</b>\n\n"
                            f"{(desc or '')[:300]}...\n\n"
                            f"🛒 <a href=\"{tracking_link}\">Перейти к офферу</a>"
                        )

                        success, msg_or_err = publish_to_telegram(bot_token, channel_id, post_text, image_url)

                        if success:
                            cursor.execute("""
                                INSERT INTO publications (material_id, channel, external_publication_id)
                                VALUES (%s, 'telegram', %s);
                            """, (material_id, msg_or_err))
                            cursor.execute("UPDATE materials SET status = 'published' WHERE id = %s;", (material_id,))
                            conn.commit()
                            logger.info(f"CPA_TELEGRAM_PUBLISHED | message_id: {msg_or_err}")
                        else:
                            cursor.execute("UPDATE materials SET status = 'failed' WHERE id = %s;", (material_id,))
                            conn.commit()
                            logger.error(f"CPA_TELEGRAM_FAILED | {msg_or_err}")

                cursor.execute("SELECT pg_advisory_unlock(%s);", (LOCK_ID,))
                conn.commit()

            conn.close()
        except Exception as e:
            logger.error(f"Autopilot loop error: {e}")

        time.sleep(7200)

# ------------------------------------------------------------------------------
# 5. WEBSERVICE (ASGI СОВМЕСТИМЫЙ С UVICORN RUN:APP)
# ------------------------------------------------------------------------------
async def app(scope, receive, send):
    if scope['type'] != 'http':
        return

    path = scope.get('path', '')
    query_string = scope.get('query_string', b'').decode('utf-8')
    params = urllib.parse.parse_qs(query_string)

    if path == '/health':
        body = json.dumps({
            "status": "live",
            "version": CPA_DISTRIBUTION_ENGINE_VERSION,
            "engine": "CPA Distribution Engine"
        }).encode('utf-8')
        
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [[b'content-type', b'application/json']]
        })
        await send({'type': 'http.response.body', 'body': body})
        return

    if path.startswith('/r/'):
        click_id = path.replace('/r/', '')
        offer_id = params.get('off', [None])[0]
        pub_id = params.get('pub', [None])[0]
        db_url = os.getenv("DATABASE_URL")

        if db_url and offer_id:
            try:
                conn = psycopg2.connect(db_url)
                cursor = conn.cursor()
                cursor.execute("SELECT affiliate_url FROM offers WHERE id = %s;", (offer_id,))
                row = cursor.fetchone()
                if row:
                    affiliate_url = row[0]
                    cursor.execute("""
                        INSERT INTO clicks (click_id, offer_id, publication_id)
                        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;
                    """, (click_id, offer_id, pub_id if pub_id else None))
                    conn.commit()
                    conn.close()

                    sep = "&" if "?" in affiliate_url else "?"
                    target_url = f"{affiliate_url}{sep}sub1={click_id}"

                    await send({
                        'type': 'http.response.start',
                        'status': 302,
                        'headers': [[b'location', target_url.encode('utf-8')]]
                    })
                    await send({'type': 'http.response.body', 'body': b''})
                    return
            except Exception as e:
                logger.error(f"Redirect error: {e}")

    await send({
        'type': 'http.response.start',
        'status': 404,
        'headers': [[b'content-type', b'text/plain']]
    })
    await send({'type': 'http.response.body', 'body': b'Not Found'})

# Запуск базы данных и фонового процесса автопилота
db_url_env = os.getenv("DATABASE_URL")
if db_url_env:
    init_db(db_url_env)

worker_thread = threading.Thread(target=autopilot_loop, daemon=True)
worker_thread.start()

logger.info(f"CPA_APP_STARTED | Engine Version: {CPA_DISTRIBUTION_ENGINE_VERSION}")
