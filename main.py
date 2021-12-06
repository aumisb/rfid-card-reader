import evdev
from evdev import InputDevice, categorize, ecodes
import asyncio
import sys
import logging
import yaml
import voluptuous as vol
import time
from kodi import Kodi
import csv
from pathlib import Path
import random

# Logging:
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
logger = logging.getLogger(__name__)

# Constants:
SCANCODES = {
    # Scancode: ASCIICode
    0: None, 1: u'ESC', 2: u'1', 3: u'2', 4: u'3', 5: u'4', 6: u'5', 7: u'6', 8: u'7', 9: u'8',
    10: u'9', 11: u'0', 12: u'-', 13: u'=', 14: u'BKSP', 15: u'TAB', 16: u'Q', 17: u'W', 18: u'E', 19: u'R',
    20: u'T', 21: u'Y', 22: u'U', 23: u'I', 24: u'O', 25: u'P', 26: u'[', 27: u']', 28: u'CRLF', 29: u'LCTRL',
    30: u'A', 31: u'S', 32: u'D', 33: u'F', 34: u'G', 35: u'H', 36: u'J', 37: u'K', 38: u'L', 39: u';',
    40: u'"', 41: u'`', 42: u'LSHFT', 43: u'\\', 44: u'Z', 45: u'X', 46: u'C', 47: u'V', 48: u'B', 49: u'N',
    50: u'M', 51: u',', 52: u'.', 53: u'/', 54: u'RSHFT', 56: u'LALT', 100: u'RALT'
}
KEY_ENTER = 'KEY_ENTER'

# Defaults:
CONFIG = '/root/magic-cards-reader/config.yaml'
DEFAULT_HOST = 'localhost'
DEFAULT_PORT = 8080
DEFAULT_TIMEOUT = 2
DEFAULT_PLAYLIST_LIMIT = 2000
DEFAULT_READER_PATH = '/dev/rfid-reader'
DEFAULT_ALBUMS_DB = Path.cwd().joinpath('albums.csv')
DEFAULT_TV_DB = Path.cwd().joinpath('tv.csv')
REQUIRED_ALBUM_DB_FIELDS = ['rf_id', 'album', 'album_artist']
REQUIRED_TV_DB_FIELDS = ['rf_id', 'show']

# Validation schemas:
# Schemas:
kodi_config_schema = vol.Schema({
    vol.Optional('host', default=DEFAULT_HOST): vol.Any(vol.Coerce(str)),
    vol.Optional('port', default=DEFAULT_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    vol.Optional('username', default='kodi'): vol.All(vol.Coerce(str)),
    vol.Optional('password', default='kodi'): vol.All(vol.Coerce(str)),
    vol.Optional('protocol', default='http'): vol.Any('http', 'https'), 
    vol.Optional('subpath', default=None): vol.Any(None,str),
    vol.Optional('timeout', default=DEFAULT_TIMEOUT): vol.All(vol.Coerce(float), vol.Range(min=0.001, max=120)),
    vol.Optional('playlist_limit', default=DEFAULT_PLAYLIST_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=2000)),
    })

reader_config_schema = vol.Schema({
    vol.Optional('path', default=DEFAULT_READER_PATH): vol.All(vol.Coerce(str)),
    })

albums_config_schema = vol.Schema({
    vol.Optional('db', default=str(DEFAULT_ALBUMS_DB)): vol.IsFile(),
    })    

tv_config_schema = vol.Schema({
    vol.Optional('db', default=str(DEFAULT_TV_DB)): vol.IsFile(),
    })    

validate_config = vol.Schema({
    vol.Required('kodi'): kodi_config_schema,
    vol.Optional('albums'): albums_config_schema,
    vol.Optional('tv'): tv_config_schema,
    vol.Optional('reader'): reader_config_schema
    })

# Helper functions
def read_input(device):
    rfid = ''
    for event in device.read_loop():
        data = categorize(event)
        if event.type == ecodes.EV_KEY and data.keystate == data.key_down:
            if data.keycode == KEY_ENTER:
                break
            rfid += SCANCODES[data.scancode]
    return rfid

# devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
# for device in devices:
#     print(device.path, device.name, device.phys)

def db_list(db_csv, required_fields):
    with open(db_csv) as f:
        db_dict = csv.DictReader(f)
        if not all(x in db_dict.fieldnames for x in required_fields):
            logger.error(f'Required fields {required_fields} in DB is/are missing!')
            return None
        else:
            return list(db_dict)

def main():
    with open(CONFIG, 'r') as stream:
        try:
            config = yaml.safe_load(stream)
            logger.debug(f'Loaded configuration file from {CONFIG}')
            valid_config = validate_config(config)
            # valid_config = config
            logger.debug('Validated configuration file.')
        except Exception as exc:
            logger.critical("Exception encountered", exc_info=True)
            return       

    reader_path = valid_config['reader']['path']
    kodi = Kodi(valid_config['kodi'])

    albums_db = db_list(valid_config['albums']['db'], REQUIRED_ALBUM_DB_FIELDS)
    tv_db = db_list(valid_config['tv']['db'], REQUIRED_TV_DB_FIELDS)

    device = evdev.InputDevice(reader_path)
    device.grab() 

    while True:
        try:
            rfid = read_input(device)
            logger.info(f"Card detected with RFID: {rfid}")
            match_album = [x for x in albums_db if x['rf_id'] == rfid]
            match_tv = [x for x in tv_db if x['rf_id'] == rfid]
            if match_album:
                album_id = None
                album = match_album[0]['album']
                artist = match_album[0]['album_artist']
                db_id_str = match_album[0]['kodi_db_id']
                logger.info(f'Album found corresponding to RFID. Album: {album} | Artist: {artist} | DB ID: {db_id_str}')
                if db_id_str:
                    logger.info(f'Kodi DB ID exists for album: {db_id_str}')
                    try:
                        album_id = int(db_id_str)
                    except ValueError:
                        logger.error(f'Could not convert Kodi DB ID to integer', exc_info=True)
                else:               
                    artist_id = kodi.FindArtist(artist)
                    if artist_id:
                        logger.info(f"Artist: {artist} has Kodi DB id of {artist_id}")
                        album_id = kodi.FindAlbum(album, artist_id[0][0])[0][0]
                if album_id:
                    kodi.ClearAudioPlaylist()
                    kodi.AddAlbumToPlaylist(album_id)
                    kodi.StartAudioPlaylist()
                    kodi.ShowMusicPlaylist()
            elif match_tv:
                show_id = None
                show = match_tv[0]['show']
                db_id_str = match_tv[0]['kodi_db_id']
                logger.info(f'TV show found corresponding to RFID. Show: {show} | DB ID: {db_id_str}')
                if db_id_str:
                    try:
                        show_id = int(db_id_str)
                    except ValueError:
                        logger.error(f'Could not convert Kodi DB ID to integer', exc_info=True)
                else:
                    show_id_search_result = kodi.FindTvShow(show)
                    if show_id_search_result:
                        show_id = show_id_search_result[0][0]
                if show_id:
                    logger.info(f'Kodi DB ID for TV show: {show_id}')
                    episodes_result = kodi.GetEpisodesFromShow(show_id)
                    episodes_array = []
                    for episode in episodes_result['result']['episodes']:
                        episodes_array.append(episode['episodeid'])
                    episode_id = random.choice(episodes_array)
                    kodi.PlayEpisode(episode_id, False)
            else:
                logger.info(f'No album or TV show found corresponding to RFID.')
            time.sleep(0.1)
        except Exception as e:
            logger.error("Critical error encountered", exc_info=e)
            device.ungrab()        
             

if __name__ == "__main__":
    main()
    



