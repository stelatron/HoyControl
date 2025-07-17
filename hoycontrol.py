

import requests
import csv
import time
import datetime
import logging
import pytz
from astral import LocationInfo
from astral.sun import sun
from xml.etree import ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logging.handlers import TimedRotatingFileHandler

# --- Configuration ---
LOGIN_URL = "https://neapi.hoymiles.com/iam/pub/0/auth/login"
TOGGLE_URL = "https://neapi.hoymiles.com/pvm-ctl/api/0/dev/command/put"
STATUS_URL = "https://neapi.hoymiles.com/pvm-ctl/api/0/dev/command/put_status"

# "inverter_data.csv" file contains the Hoymiles user credentials in the following format 
# (first line is a comment line)
# example@gmail.com,Hoymiles_username,Encoded_password,DTU_id,inverter_id
INVERTER_CSV = "inverter_data.csv"

# Provide a token that grants access to the day-ahead electricity prices on the ENTSOE website 
# The token can be requested by creating an account on the transparency.entsoe.eu website and requesting restful API access
ENTSOE_TOKEN = "ADD_YOUR_TOKEN_HERE"
ENTSOE_DOMAIN_NL = "10YNL----------L"

# Logging setup: weekly rotating log, 4 backups, no console output
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_handler = TimedRotatingFileHandler("hoymiles_price_controller_log.log", when="W0", backupCount=4, encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)

HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json",
    "Origin": "https://global.hoymiles.com",
    "Referer": "https://global.hoymiles.com/",
    "language": "en-us",
    "User-Agent": "Mozilla/5.0"
}

nl_tz = pytz.timezone("Europe/Amsterdam")

def create_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = create_session()

def get_all_prices_for_today():
    now = datetime.datetime.now(nl_tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + datetime.timedelta(days=1)

    period_start = today_start.strftime("%Y%m%d%H%M")
    period_end = today_end.strftime("%Y%m%d%H%M")

    url = "https://web-api.tp.entsoe.eu/api"
    params = {
        "securityToken": ENTSOE_TOKEN,
        "documentType": "A44",
        "in_Domain": ENTSOE_DOMAIN_NL,
        "out_Domain": ENTSOE_DOMAIN_NL,
        "periodStart": period_start,
        "periodEnd": period_end,
    }

    try:
        response = SESSION.get(url, params=params)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch ENTSO-E data: {e}")
        return []

    try:
        root = ET.fromstring(response.content)
        prices = []
        for time_series in root.findall(".//{*}TimeSeries"):
            period = time_series.find(".//{*}Period")
            start_time_str = period.find("{*}timeInterval/{*}start").text
            start_time = datetime.datetime.strptime(start_time_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=pytz.utc).astimezone(nl_tz)

            for point in period.findall("{*}Point"):
                position = int(point.find("{*}position").text)
                price_eur_per_mwh = float(point.find("{*}price.amount").text)
                hour = start_time + datetime.timedelta(hours=position - 1)
                prices.append((hour, price_eur_per_mwh / 1000.0))  # EUR/kWh

        return prices
    except Exception as e:
        logger.exception("Error parsing ENTSO-E XML response")
        return []

def find_current_price_block(prices):
    now = datetime.datetime.now(nl_tz).replace(minute=0, second=0, microsecond=0)
    current_index = next((i for i, (hour, _) in enumerate(prices) if hour == now), None)
    if current_index is None:
        return None, 0, now

    price_margin = 0.01  # [EUR/kWh] add margin in the price before turning solar panels off
    current_sign = 1 if prices[current_index][1]+price_margin >= 0 else -1
    block_hours = [prices[current_index][0]]

    for hour, price in prices[current_index + 1:]:
        if (price+price_margin >= 0) == (current_sign > 0):
            block_hours.append(hour)
        else:
            break

    return current_sign, len(block_hours), prices[current_index + len(block_hours) - 1][0]

def login(username, encrypted_password):
    payload = {"user_name": username, "password": encrypted_password}
    try:
        response = SESSION.post(LOGIN_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning(f"Login error for {username}: {e}")
        return None

    if data.get("status") == "0":
        return data["data"]["token"]
    logger.warning(f"Login failed for {username}: {data.get('message')}")
    return None

def toggle_inverter(token, dtu_sn, inverter_sn, action):
    headers = HEADERS.copy()
    headers["authorization"] = token
    payload = {
        "action": action,
        "dev_sn": inverter_sn,
        "dev_type": 3,
        "dtu_sn": dtu_sn
    }
    try:
        response = SESSION.post(TOGGLE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "0":
            return data["data"]
    except Exception as e:
        logger.error(f"Toggle error: {e}")
    return None

def check_status(token, command_id):
    headers = HEADERS.copy()
    headers["authorization"] = token
    payload = {"id": command_id}

    for _ in range(60):
        try:
            response = SESSION.post(STATUS_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "0" and data["data"].get("code") == 0:
                logger.info("✅ Inverter responded to command successfully.")
                return True
        except Exception as e:
            logger.warning(f"Error checking status: {e}")
        time.sleep(1)
    logger.warning("❌ Inverter did not respond within timeout.")
    return False

def load_inverters():
    inverters = []
    with open(INVERTER_CSV, newline="") as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)
        for row in reader:
            if len(row) != 5:
                logger.warning(f"Skipping invalid row: {row}")
                continue
            inverters.append({
                "email": row[0],
                "username": row[1],
                "password": row[2],
                "dtu_sn": row[3],
                "inverter_sn": row[4]
            })
    return inverters

def wait_until_sunrise():
    city = LocationInfo("Amsterdam", "Netherlands", "Europe/Amsterdam", 52.3676, 4.9041)
    now = datetime.datetime.now(nl_tz)
    s = sun(city.observer, date=now.date(), tzinfo=nl_tz)
    sunrise = s["sunrise"]
    if now >= sunrise:
        s = sun(city.observer, date=now.date() + datetime.timedelta(days=1), tzinfo=nl_tz)
        sunrise = s["sunrise"]

    wait_seconds = (sunrise - now).total_seconds()
    logger.info(f"Sleeping until sunrise at {sunrise} ({int(wait_seconds)} seconds)...")
    time.sleep(wait_seconds)

def is_daylight():
    city = LocationInfo("Amsterdam", "Netherlands", "Europe/Amsterdam", 52.3676, 4.9041)
    now = datetime.datetime.now(nl_tz)
    s = sun(city.observer, date=now.date(), tzinfo=nl_tz)
    return s["sunrise"] <= now <= s["sunset"]

def main_loop():
    while True:
        logger.info("=========================================")
        if not is_daylight():
            wait_until_sunrise()
            continue

        prices = get_all_prices_for_today()
        if not prices:
            logger.warning("Failed to retrieve prices. Retrying in 5 minutes.")
            time.sleep(300)
            continue

        sign, duration, last_hour = find_current_price_block(prices)
        if sign is None or duration == 0:
            logger.warning("Could not determine price block. Retrying in 5 minutes.")
            time.sleep(300)
            continue

        action_code = 6 if sign > 0 else 7
        logger.info(f"💡 Current price block is {'positive' if sign > 0 else 'negative'} for {duration} hour(s).")

        inverters = load_inverters()
        any_failure = False
        for inv in inverters:
            logger.info(f"Send {action_code} (6 = ON, 7 = OFF) to inverter {inv['inverter_sn']} for user {inv['username']}...")
            token = login(inv["username"], inv["password"])
            if not token:
                any_failure = True
                continue
            command_id = toggle_inverter(token, inv["dtu_sn"], inv["inverter_sn"], action_code)
            if command_id:
                success = check_status(token, command_id)
                if not success:
                    any_failure = True
            else:
                any_failure = True
            time.sleep(1.5)

        if any_failure:
            logger.warning("⚠️ One or more inverters failed. Sleeping for 15 minutes.")
            time.sleep(900)
        else:
            now = datetime.datetime.now(nl_tz)
            next_change_hour = last_hour + datetime.timedelta(hours=1)
            sleep_seconds = (next_change_hour - now).total_seconds()
            logger.info(f"🕒 All inverters successful. Sleeping until next price sign change at {next_change_hour} ({int(sleep_seconds)} seconds)...")
            time.sleep(max(0, sleep_seconds))

if __name__ == "__main__":
    try:
        logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.info("!!!!!!!!!!Script restarted!!!!!!!!!!!!!!!")
        logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.info("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        main_loop()
    except KeyboardInterrupt:
        logger.info("🚪 Script interrupted by user (Ctrl+C). Exiting gracefully.")
    except Exception as e:
        logger.exception("❌ Uncaught exception occurred. Script will terminate.")


