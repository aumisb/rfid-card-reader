import logging
import json
import requests

logger = logging.getLogger(__name__)

### Helper functions ###
# RPC string:
def RPCString(method, params=None, sort=None, filters=None, fields=None, limits=None, filtertype=None):
  j = {"jsonrpc": "2.0", "method": method, "id": 1}
  j["params"] = {}
  if params:
    j["params"] = params
  if sort:
    j["params"]["sort"] = sort
  if filters:
    if not filtertype:
      filtertype = "and"
    if len(filters) > 1:
      j["params"]["filter"] = {filtertype: filters}
    else:
      j["params"]["filter"] = filters[0]
  if fields:
    j["params"]["properties"] = fields
  if limits:
    j["params"]["limits"] = {"start": limits[0], "end": limits[1]}
  return json.dumps(j)

# Remove extra slashes
def http_normalize_slashes(url):
  url = str(url)
  segments = url.split('/')
  correct_segments = []
  for segment in segments:
    if segment != '':
      correct_segments.append(segment)
  first_segment = str(correct_segments[0])
  if first_segment.find('http') == -1:
    correct_segments = ['http:'] + correct_segments
  correct_segments[0] = correct_segments[0] + '/'
  normalized_url = '/'.join(correct_segments)
  return normalized_url

class Kodi:
    def __init__(self, config=None):
        self.host = config['host']
        self.port = config['port']
        self.protocol = config['protocol']
        self.username = config['username']
        self.password = config['password']
        self.subpath = config['subpath']
        self.timeout = config['timeout']
        self.playlist_limit = config['playlist_limit']

        self.logger = logger or logging.getLogger(__name__)

    def search_db(self, heard, results, search_type='label', limit=1):
        located = []
        heard_lower = heard.lower()
        for result in results:
            result_lower = result[search_type].lower()
            # Direct comparison
            if type(heard_lower) is type(result_lower):
                if result_lower == heard_lower:
                    logger.info('Found simple match on direct comparison')
                    located.append(result)
                    continue
        if not located:
            self.logger.info(f"Simple match failed.")
            return located
        else:
            self.logger.info('Best Match: "%s"', located[0][search_type])
        return located[:limit]

    def FindArtist(self, artist):
        self.logger.info(f'Searching for artist {artist}')
        located = []
        artists = self.GetMusicArtists()
        if 'result' in artists and 'artists' in artists['result']:
            ll = self.search_db(artist, artists['result']['artists'], 'artist')
            if ll:
                located = [(item['artistid'], item['label']) for item in ll]
        return located

    def FindTvShow(self, show):
        self.logger.info(f'Searching for show {show}')
        located = []
        shows = self.GetShows()
        if 'result' in shows and 'tvshows' in shows['result']:
            ll = self.search_db(show, shows['result']['tvshows'])
            if ll:
                located = [(item['tvshowid'], item['label']) for item in ll]
        return located

    def FindAlbum(self, album, artist_id=None):
        self.logger.info(f'Searching for album: {album}')
        located = []
        if artist_id:
            albums = self.GetArtistAlbums(artist_id)
        else:
            albums = self.GetAlbums()
        if 'result' in albums and 'albums' in albums['result']:
            ll = self.search_db(album, albums['result']['albums'])
            if ll:
                located = [(item['albumid'], item['label']) for item in ll]
        return located

    def AddAlbumToPlaylist(self, album_id, shuffle=False):
        songs_result = self.GetAlbumSongs(album_id)
        songs = songs_result['result']['songs']
        songs_array = []
        for song in songs:
            songs_array.append(song['songid'])
        return self.AddSongsToPlaylist(songs_array, shuffle)

    def AddSongsToPlaylist(self, song_ids, shuffle=False):
        songs_array = []
        songs_array = [dict(songid=song_id) for song_id in song_ids[:self.playlist_limit]]
        # Segment the requests into chunks that Kodi will accept in a single call
        for a in [songs_array[x:x+2000] for x in range(0, len(songs_array), 2000)]:
            self.logger.info('Adding %d items to the queue...', len(a))
            res = self.SendCommand(RPCString("Playlist.Add", {"playlistid": 0, "item": a}))
        return res
    
    def StartAudioPlaylist(self, playlist_file=None):
        if playlist_file:
            return self.SendCommand(RPCString("Player.Open", {"item": {"file": playlist_file}}), False)
        else:
            return self.SendCommand(RPCString("Player.Open", {"item": {"playlistid": 0}}), False)
    def PlayerStop(self):
        playerid = self.GetPlayerID()
        if playerid is not None:
            return self.SendCommand(RPCString("Player.Stop", {"playerid": playerid}))
    def GetPlayerID(self, player_types=['picture', 'audio', 'video']):
        data = self.SendCommand(RPCString("Player.GetActivePlayers"))
        result = data.get("result", [])
        if result:
            for r in result:
                if r.get("type") in player_types:
                    return r.get("playerid")
        return None
    def GetMusicArtists(self, sort=None, filters=None, filtertype=None, limits=None):
        return self.SendCommand(RPCString("AudioLibrary.GetArtists", {"albumartistsonly": False}, sort=sort, filters=filters, filtertype=filtertype, limits=limits))
    def GetArtistAlbums(self, artist_id):
        return self.SendCommand(RPCString("AudioLibrary.GetAlbums", filters=[{"artistid": int(artist_id)}]))
    def GetAlbums(self, sort=None, filters=None, filtertype=None, limits=None):
        return self.SendCommand(RPCString("AudioLibrary.GetAlbums", sort=sort, filters=filters, filtertype=filtertype, limits=limits))        
    def ClearVideoPlaylist(self):
        return self.SendCommand(RPCString("Playlist.Clear", {"playlistid": 1}))
    def GetAlbumSongs(self, album_id, sort=None, limits=None):
        return self.GetSongs(sort={"order": "ascending", "method": "track"}, filters=[{"albumid": int(album_id)}], limits=limits)
    def GetSongs(self, sort=None, filters=None, filtertype=None, limits=None):
        return self.SendCommand(RPCString("AudioLibrary.GetSongs", sort=sort, filters=filters, filtertype=filtertype, limits=limits))        
    def ClearAudioPlaylist(self):
        return self.SendCommand(RPCString("Playlist.Clear", {"playlistid": 0}))
    def ShowMusicPlaylist(self):
        return self.SendCommand(RPCString("GUI.ActivateWindow", {"window": "musicplaylist"}), False)
    def GetShows(self, sort=None, filters=None, filtertype=None, limits=None):
        return self.SendCommand(RPCString("VideoLibrary.GetTVShows", sort=sort, filters=filters, filtertype=filtertype, limits=limits))
    def GetEpisodesFromShow(self, show_id):
        return self.SendCommand(RPCString("VideoLibrary.GetEpisodes", {"tvshowid": int(show_id)}))
    def PlayEpisode(self, ep_id, resume=True):
        return self.SendCommand(RPCString("Player.Open", {"item": {"episodeid": ep_id}, "options": {"resume": resume}}), False)

    def SendCommand(self, command, wait_resp=True, cache_resp=False):
        # Join the configuration variables into a url
        url = f"{self.protocol}://{self.host}:{self.port}/{self.subpath or ''}/jsonrpc"
        
        # Remove any double slashes in the url
        url = http_normalize_slashes(url)
        self.logger.debug(f"Sending request to {url}")
        self.logger.debug(f"Command: {command}")

        try:
            r = requests.post(url, data=command, auth=(self.username, self.password), timeout=self.timeout)
        except requests.exceptions.ReadTimeout:
            pass
        else:
            if r.encoding is None:
                r.encoding = 'utf-8'
            try:
                return r.json()
            except:
                self.logger.error('Error: json decoding failed {}'.format(r))
                raise

