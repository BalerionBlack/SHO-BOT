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

# --- LINKS PARA DIVULGAÇÃO (CORRETOS) ---
TELEGRAM_PROMO_LINK = "https://t.me/addlist/lsXsS2hk52E4ZGNh" 
WHATSAPP_PROMO_LINK = "https://whatsapp.com/channel/0029VaKZfXb7dmeYz8Fj6e0S"

# --- ARQUIVOS E DIRETÓRIOS ---
SHOPEE_AFFILIATE_GRAPHQL_URL = "https://open-api.affiliate.shopee.com.br/graphql"
POSTED_OFFERS_FILE = 'posted_offers.json'
TEMP_IMAGE_DIR = 'temp_images'
LOG_FILE_PATH = 'bot_activity.log'
TEMPLATE_IMAGE_NAME = 'template.png'

# --- CONFIGURAÇÕES DO TEMPLATE DE IMAGEM ---
POSICAO_FOTO = (270, 95) 
TAMANHO_FOTO = (780, 540) 

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
            logging.info(f"Imagem composta salva em: {output_path}")
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
        nodes {
          itemId
          commissionRate
          priceMax
          priceMin
          imageUrl
          productName
          offerLink
        }
        pageInfo {
          page
          limit
          hasNextPage
        }
      }
    }
    """
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
    # Extrai os dados básicos
    product_name = offer_data['productName']
    affiliate_link = offer_data['offerLink']
    item_id = offer_data['itemId']
    image_url = offer_data['imageUrl']
    price_min_str = offer_data.get("priceMin")
    price_max_str = offer_data.get("priceMax")

    # Inicia a mensagem com o nome do produto em negrito (usando HTML <b>)
    mensagem_telegram = f"🔥 <b>{product_name}</b> 🔥\n\n"

    # Tenta formatar e adicionar os preços
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
        logging.warning(f"Não foi possível formatar os preços para o item {item_id}. A mensagem será enviada sem eles.")
        mensagem_telegram += "\n"
    
    # Adiciona o restante da mensagem
    mensagem_telegram += f"🛒 Compre agora 👉 {affiliate_link}\n\n"
    mensagem_telegram += "📲 𝑭𝒊𝒒𝒖𝒆 𝒑𝒐𝒓 𝒅𝒆𝒏𝒕𝒓𝒐 𝒅𝒂𝒔 𝒑𝒓𝒐𝒎𝒐𝒄‌𝒐‌𝒆𝒔:\n"
    if TELEGRAM_PROMO_LINK:
        # Adicionado \n\n para criar a linha de espaço
        mensagem_telegram += f"🔵 Telegram: {TELEGRAM_PROMO_LINK}\n\n"
    if WHATSAPP_PROMO_LINK:
        mensagem_telegram += f"🟢 Ofertas no WhatsApp: {WHATSAPP_PROMO_LINK}"

    # Prepara a imagem para envio
    image_to_send = None
    composed_image_path = None
    product_image_filepath = None

    if image_url:
        product_image_filepath = download_image(image_url, f"product_{item_id}.jpg")
    
    template_full_path = os.path.join(TEMP_IMAGE_DIR, TEMPLATE_IMAGE_NAME)
    if product_image_filepath and os.path.exists(template_full_path):
        composed_image_path = os.path.join(TEMP_IMAGE_DIR, f"composed_{item_id}.png")
        image_to_send = compose_images(template_full_path, product_image_filepath, composed_image_path)
    elif product_image_filepath:
        image_to_send = product_image_filepath

    # Envia a mensagem para o Telegram usando parse_mode='HTML'
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
        if 'parse error' in e.description.lower():
            try:
                logging.info("Falha na formatação HTML. Tentando enviar como texto plano...")
                if image_to_send:
                    with open(image_to_send, 'rb') as photo:
                        bot.sendPhoto(TELEGRAM_CHAT_ID, photo, caption=mensagem_telegram)
                else:
                    bot.sendMessage(TELEGRAM_CHAT_ID, mensagem_telegram)
                success = True
            except Exception as plain_e:
                logging.error(f"Falha ao enviar como texto plano: {plain_e}")
    except Exception as e:
        logging.error(f"Erro inesperado ao enviar '{offer_data['productName']}': {e}")
    finally:
        delete_image(product_image_filepath)
        delete_image(composed_image_path)
    return success

# ========= FUNÇÃO CORRIGIDA =========
def run_bot():
    current_page = 1
    # Vamos buscar 50 ofertas de uma vez para sermos mais eficientes
    OFFERS_PER_PAGE = 50 

    while True:
        logging.info(f"\n--- Buscando um pacote de {OFFERS_PER_PAGE} ofertas (Página: {current_page}) ---")
        offers, has_next_page = get_shopee_offers(limit=OFFERS_PER_PAGE, page=current_page)

        if not offers:
            logging.warning("Nenhuma oferta encontrada nesta página. Reiniciando a busca da página 1 em 1 minuto.")
            current_page = 1
            time.sleep(60)
            continue

        found_new_offer_in_batch = False
        for offer in offers:
            item_id = offer.get("itemId")

            if not item_id or item_id in posted_offers_ids:
                if item_id:
                    # Este log pode ser muito repetitivo, então é opcional. 
                    # logging.info(f"Oferta repetida encontrada no pacote: '{offer.get('productName')}'. Verificando a próxima...")
                    pass
                continue # Pula para a próxima oferta no pacote

            # Se chegamos aqui, a oferta é NOVA!
            found_new_offer_in_batch = True
            logging.info(f"OFERTA NOVA ENCONTRADA: '{offer.get('productName')}'")
            
            if send_telegram_offer(offer):
                posted_offers_ids.add(item_id)
                save_posted_offers()
                logging.info("Postagem OK. Aguardando 15 minutos para buscar a próxima...")
                time.sleep(900) # 15 minutos
            else:
                logging.error(f"Falha ao enviar a oferta. Tentando a próxima em 5 segundos.")
                time.sleep(5)
            
            # Depois de postar e esperar, vamos buscar um novo pacote de ofertas desde o início
            current_page = 1 
            break # Sai do loop 'for offer in offers' para reiniciar a busca com um novo pacote

        # Se o loop 'for' terminou e não achamos nenhuma oferta nova no pacote inteiro
        if not found_new_offer_in_batch:
            if has_next_page:
                logging.info(f"Nenhuma oferta nova neste pacote. Indo para a próxima página.")
                current_page += 1
            else:
                logging.info("Chegou ao fim de todas as páginas. Reiniciando da página 1 em 15 minutos.")
                current_page = 1
                time.sleep(900) # 15 minutos

if __name__ == "__main__":
    load_posted_offers()
    logging.info("Bot de ofertas Shopee iniciado.")
    logging.info(f"Carregadas {len(posted_offers_ids)} ofertas já postadas do histórico.")
    os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)
    run_bot()
