#! /usr/bin/env python3

import broadlink
import configparser
import sys
import os
import json
import aqi
import requests
import logging
from datetime import datetime, timezone
from time import sleep
from pathlib import Path

def laseregg_read(base_url,device,key):
    url = base_url.strip("/") + '/lasereggs/' + device
    params = {}
    params['key'] = key
    session = requests.session()
    try:
        response = session.get(url,params=params, headers={})
        response.raise_for_status()
    except requests.exceptions.RequestException as err:
        logging.error(err)
        return -1, -1
    data = json.loads(response.content).get('info.aqi')
    ts = (datetime.now(timezone.utc) - datetime.strptime(data['ts'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)).total_seconds()
    pm25 = data['data'].get('pm25')
    pm10 = data['data'].get('pm10')
    if pm25 is None:
        pm25_aqi = -1
    else:
        pm25_aqi = float(aqi.to_aqi([(aqi.POLLUTANT_PM25, min(500.4,pm25))]))
    if pm10 is None:
        pm10_aqi = -1
    else:
        pm10_aqi = float(aqi.to_aqi([(aqi.POLLUTANT_PM10, min(604,pm10))]))
    aqi_us = max(pm25_aqi,pm10_aqi)
    return ts, aqi_us

def send(dev, command):
    dev.send_data(bytearray.fromhex(command))

logformatstring = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
logformat = logging.Formatter(logformatstring)
logdtformat = '%m-%d %H:%M:%S'
logging.basicConfig(level=logging.DEBUG, format=logformatstring,datefmt=logdtformat)

# Load config file
config_file = Path(sys.argv[0]).resolve().parents[0] / 'config.ini'
config = configparser.ConfigParser()
config.read_file(open(config_file))

# do we log to a file as well?
try:
    Path(config['log']['logfile']).touch()
    fh = logging.FileHandler(config['log']['logfile'])
    fh.setFormatter(logformat)
    logging.getLogger().addHandler(fh)
    logging.info("Logging to %s too" % config['log']['logfile'])
except KeyError as e:
    logging.info("Config file does not specifiy existing logfile")

# Initialize blaster
try:
    devicetype = int(config['rmmini3']['type'],0)
    host = config['rmmini3']['rm_ip']
    mac = bytearray.fromhex(config['rmmini3']['rm_mac'])
except KeyError as e:
    logging.error("RM Mini 3 settings not found in config file")
    sys.exit(2)
dev = broadlink.gendevice(devicetype, (host, 80), mac)

try:
    dev.auth()
    logging.info("Successfully initialized RM Mini 3")
except broadlink.exceptions.DeviceOfflineError as e:
    logging.error("The RM2 device at %s is offline" % host)
    no_device = True
    logging.info("Trying to find RM2 device elsewhere on network")
    devices = broadlink.discover(5)
    for d in devices:
        if d.auth():
            if d.type == 'RM2':
                logging.info("Found RM2 device host %s, mac %s" % (d.host[0], ':'.join(format(x, '02x') for x in d.mac)))
                logging.info("Update config.ini file with above info for faster startup next time")
                dev = d
                no_device = False
    if no_device:
        logging.error("No RM2 device found on network, exiting.")
        sys.exit(2)

# Kaiterra device
try:
    API_BASE_URL=config['LaserEgg']['api_base_url']
    API_KEY=config['LaserEgg']['api_key']
    DEVICE_ID=config['LaserEgg']['device_id']
except KeyError as e:
    logging.error("LaserEgg settings not found in config file")
    sys.exit(2)

last_update = -1
statusfile = config['log']['statusfile']
while True:
    ts, aqi_us = laseregg_read(API_BASE_URL,DEVICE_ID,API_KEY)
    logging.info("Reading %s seconds ago, AQI: %s" % (int(ts), aqi_us))
    if ts > 60*5 or aqi_us < 0:
        str_update = "Last update " + str((datetime.now(timezone.utc) - last_update).total_seconds()) + " ago." if last_update != -1 else "Never updated"
        if ts > 60*20:
            send(dev, config['IQAir']['one'])
            logging.info("No update in 20mins, sending 1 to IQAir")
        else:
            logging.info("No update in readings, skipping. " + str_update)
        sleep(60*5)
        continue
    try:
        if aqi_us > 70:
            sent = 6
            send(dev, config['IQAir']['six'])
            logging.info("Sent 6 to ir blaster")
        elif aqi_us > 50:
            sent = 5
            send(dev, config['IQAir']['five'])
            logging.info("Sent 5 to ir blaster")
        elif aqi_us > 40:
            sent = 4
            send(dev, config['IQAir']['four'])
            logging.info("Sent 4 to ir blaster")
        elif aqi_us > 20:
            sent = 2
            send(dev, config['IQAir']['two'])
            logging.info("Sent 2 to ir blaster")
        else:
            sent = 1
            send(dev, config['IQAir']['one'])
            logging.info("Sent 1 to ir blaster")
    except Exception as err:
        logging.error(err)
        sleep(60*5)
        continue
    last_update = datetime.now(timezone.utc)
    if os.access(statusfile, os.W_OK):
        with open(statusfile,'w') as out:
            out.write('\n'.join(['Sent '+str(sent),'At '+ last_update.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)')]))
    else:
        logging.error("Statusfile %s is not writeable or does not exist" % statusfile)
    sleep(60*15)

