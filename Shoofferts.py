import requests
import time
import hashlib
import json
import logging
import os
import telepot
from telepot.exception import TelegramError
from PIL import Image

# --- CONFIGURAÇÕES GERAIS ---
SHOPEE_AFFILIATE_APP_ID = 18382050001
SHOPEE_AFFILIATE_SECRET = "QW73NP62RXOGGSTAXCBK6LEW6QE3JPHV"
TELEGRAM_BOT_TOKEN = "7920016653:AAHMbacSAzlGqOKJ1J53ePN6N11NpruvXvI"
TELEGRAM_CHAT_ID = "@cliquoucarol"

# --- LINKS PARA DIVULGAÇÃO ---
TELEGRAM_PROMO_LINK = "https://t.me/addlist/w5xyZxxVjd83MTQx"
WHATSAPP_PROMO_LINK = "https://whatsapp.com/channel/0029VaKZfXb7dmeYz8Fj6e0S"

# --- ARQUIVOS E DIRETÓRIOS ---
SHOPEE_AFFILIATE_GRAPHQL_URL = "https://open-api.affiliate.shopee.com.br/graphql"
POSTED_OFFERS_FILE = 'posted_offers.json'
TEMP_IMAGE_DIR = 'temp_images'
LOG_FILE_PATH = 'bot_activity.log'
TEMPLATE_IMAGE_PATH = 'assets/template.png'

# --- CONFIGURAÇÕES DO TEMPLATE DE IMAGEM ---
POSICAO_FOTO = (270, 95)
TAMANHO_FOTO = (780, 540)

# --- CONFIGURAÇÕES DE EXECUÇÃO ---
# [ALTERAÇÃO 1]: O filtro de comissão foi removido da lógica do bot.
# COMISSAO_MINIMA_PERCENTUAL = 8.0 
INTERVALO_ENTRE_POSTS_SEG = 900
INTERVALO_ENTRE_CICLOS_SEG = 900
OFERTAS_POR_PAGINA = 50
# [ALTERAÇÃO 2]: O número de páginas a verificar foi reduzido para 5.
PAGINAS_A_VERIFICAR = 5

# --- FIM DAS CONFIGURAÇÕES ---

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

posted_offers_ids = set()

try:
    bot = telepot.Bot(TELEGRAM_BOT_TOKEN)
except Exception as e:
    logging.critical(f"Falha ao inicializar o bot do Telegram. Erro: {e}")
    exit()

def compose_images(template_path, product_path, output_path):
    try:
        with Image.open(template_path).convert("RGBA") as template, \
             Image.open(product_path).convert("RGBA") as product_img:
            product_img.thumbnail(TAMANHO_FOTO, Image.Resampling.LANCZOS)
            template.paste(product_img, POSICAO_FOTO, product_img)
            template.save(output_path, "PNG")
            return output_path
    except FileNotFoundError:
        logging.warning(f"Arquivo template '{template_path}' ou produto '{product_path}' não encontrado.")
        return None
    except Exception as e:
        logging.error(f"Erro ao compor imagens: {e}")
        return None

def load_posted_offers():
    global posted_offers_ids
    if os.path.exists(POSTED_OFFERS_FILE):
        try:
            with open(POSTED_OFFERS_FILE, 'r', encoding='utf-8') as f:
                posted_offers_ids = set(json.load(f))
        except (json.JSONDecodeError, TypeError):
            posted_offers_ids = set()

def save_posted_offers():
    try:
        with open(POSTED_OFFERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(posted_offers_ids), f, indent=4)
    except IOError as e:
        logging.error(f"Erro ao salvar ofertas: {e}")

def generate_shopee_signature(payload_json_str):
    timestamp = int(time.time())
    factor = f"{SHOPEE_AFFILIATE_APP_ID}{timestamp}{payload_json_str}{SHOPEE_AFFILIATE_SECRET}"
    signature = hashlib.sha256(factor.encode('utf-8')).hexdigest()
    return timestamp, signature

def get_shopee_offers(limit=50, page=1):
    query_graphql = """
    query productOfferV2($limit: Int, $page: Int, $listType: Int, $sortType: Int, $isAMSOffer: Boolean) {
        productOfferV2(limit: $limit, page: $page, listType: $listType, sortType: $sortType, isAMSOffer: $isAMSOffer) {
            nodes { itemId commissionRate priceMax priceMin imageUrl productName offerLink }
            pageInfo { hasNextPage }
        }
    }"""
    variables = {"limit": limit, "page": page, "listType": 1, "sortType": 2, "isAMSOffer": True}
    payload_dict = {"query": query_graphql, "variables": variables}
    payload_json_str = json.dumps(payload_dict, separators=(',', ':'))
    timestamp, sign = generate_shopee_signature(payload_json_str)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={SHOPEE_AFFILIATE_APP_ID}, Timestamp={timestamp}, Signature={sign}"
    }
    try:
        response = requests.post(SHOPEE_AFFILIATE_GRAPHQL_URL, headers=headers, data=payload_json_str, timeout=20)
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            logging.error(f"Erro GraphQL: {result['errors']}")
            return [], False
        shopee_data = result.get("data", {}).get("productOfferV2", {})
        offers = shopee_data.get("nodes", [])
        has_next_page = shopee_data.get("pageInfo", {}).get("hasNextPage", False)
        return offers, has_next_page
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro de requisição: {e}")
        return [], False

def download_image(url, filename):
    os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)
    filepath = os.path.join(TEMP_IMAGE_DIR, filename)
    try:
        response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status()
        with open(filepath, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=8192):
                out_file.write(chunk)
        return filepath
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao baixar imagem: {e}")
        return None

def delete_image(filepath):
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError as e:
            logging.warning(f"Erro ao remover imagem: {e}")

def send_telegram_offer(offer_data):
    product_name = offer_data['productName']
    affiliate_link = offer_data['offerLink']
    item_id = offer_data['itemId']
    image_url = offer_data['imageUrl']
    price_min_str = offer_data.get("priceMin")
    price_max_str = offer_data.get("priceMax")
    commission_rate = float(offer_data.get('commissionRate', 0))
    mensagem_telegram = f"🔥 <b>{product_name}</b> 🔥\n\n"
    try:
        price_min = float(price_min_str)
        price_max = float(price_max_str)
        if price_max > price_min:
            preco_antigo_f = f"{price_max:.2f}".replace('.', ',')
            preco_novo_f = f"{price_min:.2f}".replace('.', ',')
            mensagem_telegram += f"📉 De R$ {preco_antigo_f}\n"
            mensagem_telegram += f"✅ <b>Por R$ {preco_novo_f}</b> 🤑\n\n"
        else:
            preco_final_f = f"{price_min:.2f}".replace('.', ',')
            mensagem_telegram += f"✅ <b>Por R$ {preco_final_f}</b> 🤑\n\n"
    except (ValueError, TypeError, AttributeError):
        mensagem_telegram += "\n"
    mensagem_telegram += f"Comissão: {commission_rate}%\n"
    mensagem_telegram += f"🛒 Compre agora 👉 {affiliate_link}\n\n"
    mensagem_telegram += "📲 𝑭𝒊𝒒𝒖𝒆 𝒑𝒐𝒓 𝒅𝒆𝒏𝒕𝒓𝒐 𝒅𝒂𝒔 𝒑𝒓𝒐𝒎𝒐𝒄‌𝒐‌𝒆𝒔:\n"
    if TELEGRAM_PROMO_LINK:
        mensagem_telegram += f"🔵 Telegram: {TELEGRAM_PROMO_LINK}\n\n"
    if WHATSAPP_PROMO_LINK:
        mensagem_telegram += f"🟢 Ofertas no WhatsApp: {WHATSAPP_PROMO_LINK}"
    image_to_send, composed_image_path, product_image_filepath = None, None, None
    if image_url:
        product_image_filepath = download_image(image_url, f"product_{item_id}.jpg")
    if product_image_filepath and os.path.exists(TEMPLATE_IMAGE_PATH):
        composed_image_path = os.path.join(TEMP_IMAGE_DIR, f"composed_{item_id}.png")
        image_to_send = compose_images(TEMPLATE_IMAGE_PATH, product_image_filepath, composed_image_path)
    elif product_image_filepath:
        image_to_send = product_image_filepath
    success = False
    try:
        if image_to_send:
            with open(image_to_send, 'rb') as photo:
                bot.sendPhoto(TELEGRAM_CHAT_ID, photo, caption=mensagem_telegram, parse_mode='HTML')
        else:
            bot.sendMessage(TELEGRAM_CHAT_ID, mensagem_telegram, parse_mode='HTML')
        logging.info(f"Oferta '{offer_data['productName']}' postada com SUCESSO.")
        success = True
    except TelegramError as e:
        logging.error(f"Erro Telegram ao enviar '{offer_data['productName']}': {e.description}")
    except Exception as e:
        logging.error(f"Erro inesperado ao enviar '{offer_data['productName']}': {e}")
    finally:
        delete_image(product_image_filepath)
        delete_image(composed_image_path)
    return success

def run_bot():
    total_produtos_a_verificar = OFERTAS_POR_PAGINA * PAGINAS_A_VERIFICAR
    while True:
        logging.info(f"\n--- FASE 1: COLETA | Verificando até {total_produtos_a_verificar} produtos... ---")
        novas_ofertas_coletadas = []
        for page_num in range(1, PAGINAS_A_VERIFICAR + 1):
            logging.info(f"Coletando ofertas... Página {page_num}/{PAGINAS_A_VERIFICAR}")
            offers, has_next_page = get_shopee_offers(limit=OFERTAS_POR_PAGINA, page=page_num)
            if not offers:
                logging.warning("Nenhuma oferta retornada pela API nesta página. Continuando...")
                continue
            
            for offer in offers:
                item_id = offer.get("itemId")

                # [ALTERAÇÃO]: A verificação de comissão mínima foi removida daqui.
                # Agora, a única verificação é se a oferta já foi postada antes.
                if not item_id or item_id in posted_offers_ids:
                    continue
                
                novas_ofertas_coletadas.append(offer)
                posted_offers_ids.add(item_id)
            
            if not has_next_page:
                logging.info("API informou que não há mais páginas. Encerrando fase de coleta.")
                break
            
            time.sleep(1)

        if novas_ofertas_coletadas:
            logging.info(f"--- FASE 2: POSTAGEM | {len(novas_ofertas_coletadas)} novas ofertas serão publicadas. ---")
            
            for i, offer in enumerate(novas_ofertas_coletadas):
                logging.info(f"Postando oferta {i+1}/{len(novas_ofertas_coletadas)}: '{offer.get('productName')}'")
                
                if send_telegram_offer(offer):
                    save_posted_offers() 
                    if i < len(novas_ofertas_coletadas) - 1:
                        logging.info(f"Aguardando {INTERVALO_ENTRE_POSTS_SEG // 60} minutos para o próximo post.")
                        time.sleep(INTERVALO_ENTRE_POSTS_SEG)
                else:
                    logging.error(f"Falha ao enviar a oferta. A oferta será pulada.")
                    posted_offers_ids.remove(offer.get("itemId"))
                    save_posted_offers()
        else:
            logging.info("--- FASE DE COLETA CONCLUÍDA: Nenhuma oferta nova encontrada. ---")

        logging.info(f"Ciclo concluído. Aguardando {INTERVALO_ENTRE_CICLOS_SEG // 60} minutos para um novo ciclo de coleta.")
        time.sleep(INTERVALO_ENTRE_CICLOS_SEG)

if __name__ == "__main__":
    load_posted_offers()
    logging.info("Bot de ofertas Shopee iniciado.")
    logging.info(f"Carregadas {len(posted_offers_ids)} ofertas já postadas do histórico.")
    os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)
    os.makedirs('assets', exist_ok=True)
    run_bot()
