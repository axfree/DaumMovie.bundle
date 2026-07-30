# -*- coding: utf-8 -*-
# Daum Movie

import urllib, urlparse, unicodedata, os, time, traceback
from Framework.exceptions import RedirectError

DAUM_MOVIE_SRCH   = "https://search.daum.net/search?w=tot&q=%s&rtmaxcoll=EM1"
# DAUM_MOVIE_SGST   = "https://dapi.kakao.com/suggest-hub/v1/search.json?service=movie-v2&cate=movie&multiple=1&q=%s"

DAUM_MOVIE_DETAIL = "https://search.daum.net/search?w=cin&q=%s&coll=movie-main&spId=%s&spt=%s&DA=EM1&rtmaxcoll=EM1"

DAUM_TV_SRCH      = "https://search.daum.net/search?w=tv&q=%s"
DAUM_TV_DETAIL    = "https://search.daum.net/search?w=tv&q=%s&coll=tv-main&spId=%s&spt=tv-info&DA=TVP&rtmaxcoll=TVP"

IMDB_TITLE_SRCH   = "http://www.google.com/search?q=site:imdb.com+%s"
TVDB_TITLE_SRCH   = "http://thetvdb.com/api/GetSeries.php?seriesname=%s"

RE_YEAR_IN_NAME   =  Regex('\((\d+)\)')
RE_MOVIE_ID       =  Regex("movieId=(\d+)")
RE_TV_ID          =  Regex("tvProgramId=(\d+)")
RE_PHOTO_SIZE     =  Regex("/C\d+x\d+/")
RE_IMDB_ID        =  Regex("/(tt\d+)/")

JSON_MAX_SIZE     = 10 * 1024 * 1024

DAUM_CR_TO_MPAA_CR = {
    u'전체관람가': {
        'KMRB': 'kr/A',
        'MPAA': 'G'
    },
    u'12세이상관람가': {
        'KMRB': 'kr/12',
        'MPAA': 'PG'
    },
    u'15세이상관람가': {
        'KMRB': 'kr/15',
        'MPAA': 'PG-13'
    },
    u'청소년관람불가': {
        'KMRB': 'kr/R',
        'MPAA': 'R'
    },
    u'제한상영가': {     # 어느 여름날 밤에 (2016)
        'KMRB': 'kr/X',
        'MPAA': 'NC-17'
    }
}

def Start():
  HTTP.CacheTime = CACHE_1HOUR * 12
  HTTP.Headers['Accept'] = 'text/html, application/json'

  if Prefs['http_proxy']:
    os.environ['http_proxy'] = Prefs['http_proxy'].strip()
  if Prefs['https_proxy']:
    os.environ['https_proxy'] = Prefs['https_proxy'].strip()

def downloadImage(url, fetchContent=True):
  if Prefs['use_https_for_image']:
    url = url.replace('http://', 'https://')

  try:
    result = HTTP.Request(url, timeout=60, cacheTime=0, immediate=fetchContent)
  except Ex.HTTPError as e:
    Log('HTTPError %s: %s' % (e.code, e.message))
    return None
  except Exception as e:
    Log('Problem with the request: %s' % e.message)
    return None

  if fetchContent:
    try:
      result = result.content
    except Exception as e:
      Log('Content Error (%s) - %s' % (e, e.message))

  return result

def originalImageUrlFromCdnUrl(url):
  if 'daumcdn.net' in url or 'kakaocdn.net' in url:
    url = urllib.unquote(Regex('fname=(.*)').search(url).group(1))

  if url.startswith('//'):
    url = ( 'http:', 'https:' )[Prefs['use_https_for_image']] + url

  return url

def levenshteinRatio(first, second):
  return 1 - (Util.LevenshteinDistance(first, second) / float(max(len(first), len(second))))

def containsHangul(text):
  # return any(ord(c) >= 44032 and ord(c) <= 55203 for c in text)
  for c in list(text):
    if ord(c) >= 44032 and ord(c) <= 55203:
      return True
  return False

####################################################################################################
def searchDaumMovie(results, media, lang):
  # media_ids = []
  items = []

  # 영화 검색 (메인)
  media_name = unicodedata.normalize('NFC', unicode(media.name)).strip()
  media_words = media_name.split(' ') if containsHangul(media_name) else [ media_name ]
  while media_words:
    media_name = ' '.join(media_words)
    Log.Debug("search: %s %s" %(media_name, media.year))
    try:
      # https://search.daum.net/search?w=tot&q=서울의%20봄&rtmaxcoll=EM1
      html = HTML.ElementFromURL(DAUM_MOVIE_SRCH % urllib.quote(media_name.encode('utf8')), sleep=0.5)
      for em1Coll in html.xpath('//div[@id="em1Coll"]'):
        ctitle = em1Coll.xpath('.//div[@class="area_tit"]//a')[0]
        try:
          etitle, year = Regex('^(.*?), (\d{4})$').search(em1Coll.xpath('.//div[@class="area_tit"]//span[@class="txt_split"]')[0].text.strip()).group(1, 2) # 12.12: THE DAY, 2023
        except:
          etitle, year = None, None

        if not year:
          for oaa in em1Coll.xpath(u'.//dt[.="개봉" or .="재개봉"]/following-sibling::dd[1]/span'):
            year = Datetime.ParseDate(oaa.text).date().year

        items.append({
          'id': Regex('spId=(\d+)').search(ctitle.get('href')).group(1),
          'title': ctitle.text.strip(),
          'year': year  # em1Coll.xpath(u'.//c-doc-content/c-list-grid-desc/dt[.="개봉" or .="재개봉"]/following-sibling::dd[1]/span/text()')[0][:4]
        })

        # 영화검색 > 시리즈
        for series_a in em1Coll.xpath(u'.//a[.="시리즈"]'):
          page = HTTP.Request(urlparse.urljoin(DAUM_MOVIE_SRCH, series_a.get('href'))).content
          for series in JSON.ObjectFromString(Regex(r'const RAW_SERIES = (\[{.*?}\]); ').search(page).group(1)):
            items.append({
              'id': str(series['movieId']),
              'title': series['koreanTitle'],
              'year': str(series['productionYear']),
            })

        # 영화검색 > 동명영화
        # https://search.daum.net/search?w=tot&q=%EC%97%B0%EC%9D%B8&rtmaxcoll=EM1
        for li in em1Coll.xpath(u'.//div[@class="c-comp-similar"]//ul/li'):
          a = li.xpath('.//div[@class="item-title"]//a')[0]
          items.append({
            'id': Regex('spId=(\d+)').search(a.get('href')).group(1),
            'title': a.text.strip(),
            'year': li.xpath('.//div[@class="item-contentss"]/span/text()')[0]
          })

      if items: break

      if containsHangul(media_words.pop()):
        break

    except:
      Log.Debug(''.join(traceback.format_exc()))
      break

  if not items:
    Log.Debug('No movie matches found')
    return

  for item in items:
    score = int(levenshteinRatio(media_name, item['title']) * 80)
    if media.year and item['year']:
      score += (2 - min(2, abs(int(media.year) - int(item['year'])))) * 10
    Log.Debug('ID=%s, media_name=%s, title=%s, year=%s, score=%d' %(item['id'], media_name, item['title'], item['year'], score))
    results.Append(MetadataSearchResult(id=item['id'], name=item['title'], year=item['year'], score=score, lang=lang))

def searchDaumTV(results, media, lang):
  media_name = unicodedata.normalize('NFC', unicode(media.show)).strip()
  media_year = media.year
  # if not media_year and media.filename:
  #   match = Regex('\D(\d{2})[01]\d[0-3]\d\D').search(os.path.basename(urllib.unquote(media.filename)))
  #   if match:
  #     media_year = '20' + match.group(1)
  Log.Debug("search: %s %s" %(media_name, media_year))

  # TV검색
  html = HTML.ElementFromURL(DAUM_TV_SRCH % urllib.quote(media_name.encode('utf8')))
  for script in html.xpath('//script[starts-with(.," location.replace")]'):
    try:
      loc = Regex('location.replace\("(.*?)"\)').search(script.text).group(1)
      html = HTML.ElementFromURL('https://search.daum.net' + loc)
    except: pass

  try:
    tvp = html.xpath('//div[@id="tvpColl"]')[0]
  except:
    Log.Debug('No TV matches found')
    return

  items = []

  title, id = Regex('q=(.*?)&coll=(.*?)&spId=(\d+)&spt=(.*?)&').search(tvp.xpath('//div[@class="area_tit"]//a/@href')[0]).group(1, 3)
  title = urllib.unquote(title)
  try:
    year = Regex('(\d{2})\.\d{2}\.\d{2}\. ~').search(' | '.join(tvp.xpath('//div[@class="area_tit"]//span[@class="txt_info"]/span/text()'))).group(1)
    year = '20' + year if int(year) < 69 else '19' + year
  except: year = None
  items.append({ 'id': id, 'title': title, 'year': year })

  # TV검색 > 시리즈
  # 낭만닥터 김사부 (2016)
  series_a = tvp.xpath(u'//div[@class="c-section-tab"]//li/a[.="시리즈"]')
  if series_a:
    html = HTML.ElementFromURL('https://search.daum.net/search%s' % series_a[0].get('href'))
    for li in html.xpath('//div[@id="tvpColl"]//div[@class="cont_pannel cont_clip"]//li'):
      a = li.xpath('.//div[@class="item-title"]//a')[0]
      id = Regex('spId=(\d+)').search(a.get('href')).group(1)
      title = a.text.strip()
      try:
        year = Regex('(\d{4})\.\d{2}').search(li.xpath('.//div[@class="item-contents"]//span')[0].text).group(1)
      except: year = None
      items.append({ 'id': id, 'title': title, 'year': year })

  # TV검색 > 동명프로그램
  # 연인 (2023), 굿 파트너 (2024)
  for div in tvp.xpath(u'//div[@class="cont_pannel"]/strong[.="동명프로그램"]/following-sibling::div//div[@class="item-bundle-mid"]'):
    a = div.xpath('./div[@class="item-title"]//a')[0]
    id = Regex('spId=(\d+)').search(a.get('href')).group(1)
    title = a.text.strip()
    try:
      year = Regex(', (\d{4})\.').search(div.xpath('./div[@class="item-contents"]//dd[@class="program"]/text()[normalize-space()]')[0]).group(1)
    except: year = None
    items.append({ 'id': id, 'title': title, 'year': year })

  for idx, item in enumerate(items):
    score = int(levenshteinRatio(media_name, item['title']) * 90)
    if media_year and item['year']:
      score += (2 - min(2, abs(int(media_year) - int(item['year'])))) * 5
    Log.Debug('ID=%s, media_name=%s, title=%s, year=%s, score=%d' %(item['id'], media_name, item['title'], item['year'], score))
    results.Append(MetadataSearchResult(id=item['id'], name=item['title'], year=item['year'], score=score, lang=lang))

def updateDaumMovie(metadata, media):
  # (1) from detail page
  try:
    # 영화검색 > 정보
    # https://search.daum.net/search?w=cin&q=왕과%20사는%20남자&coll=movie-main&spId=187396&spt=movie-info&DA=EM1&rtmaxcoll=EM1
    detail = HTML.ElementFromURL(DAUM_MOVIE_DETAIL % (urllib.quote(media.title.encode('utf8')), metadata.id, 'movie-info'))

    card = detail.xpath('//div[@id="em1Coll"]/div[@class="card_comp"]')[0]

    metadata.title = card.xpath('.//div[@class="area_tit"]//a')[0].text
    metadata.title_sort = unicodedata.normalize('NFD' if Prefs['use_title_decomposition'] else 'NFC', metadata.title)
    try:
      match = Regex('^(.*?), (\d{4})$').search(card.xpath('.//div[@class="area_tit"]//span[@class="txt_split"]')[0].text.strip()) # The King's Warden, 2026
      if match:
        metadata.original_title = match.group(1)
    except: pass

    # 평점
    for cstar in card.xpath(u'.//div[@class="item-title" and ./strong/span[text()="전문가 평점"]]/following-sibling::div[1]//span[@class="gem-star-point"]/text()[last()]'):
      metadata.rating = float(cstar)

    # 장르
    metadata.genres.clear()
    for genres in card.xpath(u'.//dt[.="장르"]/following-sibling::dd[1]/span'):
      for genre in genres.text.strip().split('/'):  # 액션/어드벤처/SF
        metadata.genres.add(genre)

    # 국가
    metadata.countries.clear()
    for countries in card.xpath(u'.//dt[.="국가"]/following-sibling::dd[1]/span'):
      for country in countries.text.strip().split(', '):  # 미국, 중국
        metadata.countries.add(country)

    # 줄거리
    for summary in card.xpath('.//p[@class="desc_story mg_cont"]'):
      metadata.summary = summary.text.strip()

    # 포스터
    for poster_url in card.xpath('.//div[@class="item-thumb"]//img/@data-original-src'):
      poster_url = originalImageUrlFromCdnUrl(poster_url)
      if poster_url not in metadata.posters:
        try:
          metadata.posters[poster_url] = Proxy.Preview(HTTP.Request(poster_url, cacheTime=0), sort_order=len(metadata.posters) + 1)
        except: pass

    # 개봉, 재개봉: 2016.08.24.
    for oaa in card.xpath(u'.//dt[.="개봉" or .="재개봉"]/following-sibling::dd[1]/span'):
      metadata.originally_available_at = Datetime.ParseDate(oaa.text).date()

    # 시간: 141분, 115분 (재)
    for dd in card.xpath(u'.//dt[.="시간"]/following-sibling::dd[1]/span'):
      match = Regex(u'^(\d+)분').search(dd.text)
      if match:
        metadata.duration = int(match.group(1)) * 60 * 1000

    # 등급: 12세이상 관람가, 청소년관람불가 (재)
    for dd in card.xpath(u'.//dt[.="등급"]/following-sibling::dd[1]/span'):
      match = Regex('^(.*?)(?: \((.*?)\))?$').search(dd.text)
      if match:
        rating = match.group(1).replace(' ', '')
        if rating in DAUM_CR_TO_MPAA_CR:
          metadata.content_rating = DAUM_CR_TO_MPAA_CR[rating]['MPAA' if Prefs['use_mpaa'] else 'KMRB']
        else:
          metadata.content_rating = 'kr/' + rating

    # Log.Debug('genre=%s, country=%s' %(','.join(g for g in metadata.genres), ','.join(c for c in metadata.countries)))
    # Log.Debug('oaa=%s, duration=%s, content_rating=%s' %(metadata.originally_available_at, metadata.duration, metadata.content_rating))

  except:
    Log.Debug(''.join(traceback.format_exc()))

  # (2) cast crew
  directors = list()
  producers = list()
  writers = list()
  roles = list()

  # 영화검색 > 출연/제작
  page = HTTP.Request(DAUM_MOVIE_DETAIL % (urllib.quote(media.title.encode('utf8')), metadata.id, 'movie-casting')).content

  for row in JSON.ObjectFromString(Regex(r'const RAW_CASTS = (\[.*?\]); ').search(page).group(1)):
    for item in row['casts']:
      cast = dict()
      cast['name'] = item['person']['koreanName']
      if 'imageUrl' in item['person']: 
        cast['photo'] = item['person']['imageUrl']

      if item['jobRole'] == '감독':
        directors.append(cast)
      elif item['jobRole'] in [ '주연', '출연', '특별출연', '우정출연' ]:
        cast['role'] = item['playRole'] if 'playRole' in item else item['jobRole']
        roles.append(cast)
      else: Log.Debug('Unknown jobRole=%s' %item['jobRole'])

  for row in JSON.ObjectFromString(Regex(r'const RAW_CREWS = (\[.*?\]); ').search(page).group(1)):
    for item in row['crews']:
      crew = dict()
      crew['name'] = item['person']['koreanName']
      if 'imageUrl' in item['person']: 
        crew['photo'] = item['person']['imageUrl']

      if item['jobRole'] == '제작':
        producers.append(crew)
      elif item['jobRole'] in [ '각본', '원작' ]:
        writers.append(crew)
      # 조명, 음악, 편집, 미술, 의상/분장

  for row in JSON.ObjectFromString(Regex(r'const RAW_COMPANIES = (\[.*?\]); ').search(page).group(1)):
    # ["type"] : "제작", "배급", "제공"
    for item in row['companies']:
      if row['type'] == '배급':
        metadata.studio = item['koreanName']

  if directors:
    metadata.directors.clear()
    for director in directors:
      meta_director = metadata.directors.new()
      if 'name' in director:
        meta_director.name = director['name']
      if 'photo' in director:
        meta_director.photo = director['photo']
  if producers:
    metadata.producers.clear()
    for producer in producers:
      meta_producer = metadata.producers.new()
      if 'name' in producer:
        meta_producer.name = producer['name']
      if 'photo' in producer:
        meta_producer.photo = producer['photo']
  if writers:
    metadata.writers.clear()
    for writer in writers:
      meta_writer = metadata.writers.new()
      if 'name' in writer:
        meta_writer.name = writer['name']
      if 'photo' in writer:
        meta_writer.photo = writer['photo']
  if roles:
    metadata.roles.clear()
    for role in roles:
      meta_role = metadata.roles.new()
      if 'role' in role:
        meta_role.role = role['role']
      if 'name' in role:
        meta_role.name = role['name']
      if 'photo' in role:
        meta_role.photo = role['photo']

  # 영화검색 > 포토
  detail = HTML.ElementFromURL(DAUM_MOVIE_DETAIL % (urllib.quote(media.title.encode('utf8')), metadata.id, 'movie-photo'))

  for card in detail.xpath('//div[@id="em1Coll"]//div[@class="cont_photo"]'):
    tit = card.xpath('./div[@class="c-tit-section"]/h3')[0].text
    for photo in JSON.ObjectFromString(card.xpath('.//script')[0].text)['dataSource']:
      src = photo['src']
      if tit == '스틸':
        if src not in metadata.art:
          try:
            metadata.art[src] = Proxy.Preview(HTTP.Request(src, cacheTime=0, sleep=0.5), sort_order=len(metadata.art) + 1)
          except: pass
      elif tit == '포스터':
        if src not in metadata.posters:
          try:
            metadata.posters[src] = Proxy.Preview(HTTP.Request(src, cacheTime=0, sleep=0.5), sort_order=len(metadata.posters) + 1)
          except: pass

  Log.Debug('Total %d posters, %d artworks' %(len(metadata.posters), len(metadata.art)))

def updateDaumTV(metadata, media):
  def metadata_for(season, ep): 
    return metadata.seasons[season].episodes[ep] if season in metadata.seasons and ep in metadata.seasons[season].episodes else None
  
  def episode_set_directors(episode, directors):
    if directors:
      episode.directors.clear()
      for director in directors:
        meta_director = episode.directors.new()
        if 'name' in director:
          meta_director.name = director['name']
        if 'photo' in director:
          meta_director.photo = director['photo']

  def episode_set_writers(episode, writers):
    if writers:
      episode.writers.clear()
      for writer in writers:
        meta_writer = episode.writers.new()
        if 'name' in writer:
          meta_writer.name = writer['name']
        if 'photo' in writer:
          meta_writer.photo = writer['photo']

  # (1) from detail page
  try:
    html = HTML.ElementFromURL(DAUM_TV_DETAIL % (urllib.quote(media.title.encode('utf8')), metadata.id))
    #metadata.title = html.xpath('//div[@class="tit_program"]/strong')[0].text
    metadata.title = media.title
    metadata.title_sort = unicodedata.normalize('NFD' if Prefs['use_title_decomposition'] else 'NFC', metadata.title)
    metadata.original_title = ''
    metadata.rating = None

    metadata.genres.clear()

    # 예능 | 14부작 | 24.11.15. ~ 25.01.17. | 완결
    # 예능 | 22.06.06. ~
    # 드라마 | 7부작 | 24.12.26. | 완결
    # 8부작 | 25.01.24. | 완결
    # 미국드라마 | 25부작 | 94.09.19. ~ 95.05.18. | 완결
    txt_infos = ' | '.join(html.xpath('//div[@class="area_tit"]/div[@class="sub_header"]//span[@class="txt_info"]//text()'))
    genre, eps, oaa = Regex(u'^(?:(예능|드라마|미국드라마) \| )?(?:(\d+)부작 \| )?(\d{2}\.\d{2}\.\d{2}\.)[ ~\d.]*(?: \| (완결))?$').search(txt_infos).group(1, 2, 3)
    if genre:
      metadata.genres.add(genre)
    metadata.originally_available_at = Datetime.ParseDate(oaa, '%y.%m.%d.').date()

    # txt_infos = html.xpath('//div[@class="area_tit"]/div[@class="sub_header"]//span[@class="txt_info"]')
    # for idx, txt_info in enumerate(txt_infos):
    #   a = txt_info.xpath('./a')
    #   if a:
    #     metadata.genres.add(a[0].text)   # 드라마 or 예능
    #   else:
    #     match = Regex('^(\d{2}\.\d{2}\.\d{2}\.)').search(txt_info.xpath('./span')[0].text)
    #     if match:
    #       metadata.originally_available_at = Datetime.ParseDate(match.group(1), '%y.%m.%d.').date()

    metadata.studio = html.xpath(u'//dt[.="편성"]/following-sibling::dd//a')[0].text
    metadata.summary = html.xpath(u'//dt[.="소개"]/following-sibling::dd//p[contains(@class,"desc_story")]')[0].text.strip()

    # https://search1.kakaocdn.net/thumb/C208x290.q85/?fname=http%3A%2F%2Ft1.daumcdn.net%2Fcontentshub%2Fsdb%2Fe1369dc1d18bb3ec780a942ef9b3c81eda47065fd64c8f7162ce302420366d30
    #   http://t1.daumcdn.net/contentshub/sdb/e1369dc1d18bb3ec780a942ef9b3c81eda47065fd64c8f7162ce302420366d30
    poster_url = html.xpath('//div[contains(@class,"cont_pannel")]//div[@class="item-thumb"]//img/@data-original-src')
    if poster_url:
      poster_url = originalImageUrlFromCdnUrl(poster_url[0])
      if poster_url not in metadata.posters:
        try:
          metadata.posters[poster_url] = Proxy.Preview(HTTP.Request(poster_url, cacheTime=0), sort_order=len(metadata.posters) + 1)
        except: pass
  except Exception as e:
    Log.Debug(repr(e))
    pass

  # (2) cast crew
  directors = list()
  producers = list()
  writers = list()
  roles = list()

  # TV검색 > 출연
  cast_a = html.xpath(u'//div[@class="c-section-tab"]//li/a[.="출연"]')
  if cast_a:
    # https://search.daum.net/search?w=tv&q=%EC%97%B0%EC%9D%B8%20%EC%B6%9C%EC%97%B0%EC%A7%84&coll=tv-main&spId=94848&spt=tv-casting&DA=TVP&rtmaxcoll=TVP
    page = HTML.ElementFromURL('https://search.daum.net/search%s' % cast_a[0].get('href'), cacheTime=0)
    for li in page.xpath(u'//div[@id="tvpColl"]//div[@class="cont_pannel cont_cast"]//div[@data-tab="제작"]//li'):
      try:
        role = li.xpath('.//div[@class="item-contents"]/span')[0].text.strip()
        photo = li.xpath('.//div[@class="item-thumb"]//img/@data-original-src')[0]
        cast = dict()
        cast['name'] = li.xpath('.//div[@class="item-title"]/span')[0].text.strip()
        cast['photo'] = originalImageUrlFromCdnUrl(photo) if photo != 'thumb_noimg' else None

        if role in [u'감독', u'연출', u'조감독']:
          directors.append(cast)
        elif role in [u'제작', u'프로듀서', u'책임프로듀서', u'기획']:
          producers.append(cast)
        elif role in [u'극본', u'각본', u'원작', u'작가']:
          writers.append(cast)
        else:
          Log.Debug('Unknown role %s' % role)
      except: pass

    lis = page.xpath(u'//div[@id="tvpColl"]//div[@class="cont_pannel cont_cast"]//div[@data-tab="출연"]//li')
    if page.xpath(u'.//span[@class="ico-pmp" and text()="펼쳐보기"]'):
      # TV검색 > 출연 > 펼쳐보기
      scripts = '\n'.join(page.xpath('//script/text()'))
      qsearch = {
        'mk': Regex('var mk = "(.*?)";').search(scripts).group(1), 
        'uk': Regex('var uk = "(.*?)";').search(scripts).group(1),
        'ksk': Regex('var ksk = "(.*?)";').search(scripts).group(1)
      }
      qsearch.update(JSON.ObjectFromString(Regex('qsearch: ({.*?}),').search(scripts).group(1)))

      # ER 시즌 1, 연인 (2023)
      while True:
        qsearch2 = JSON.ObjectFromURL('https://search.daum.net/qsearch2?' + urllib.urlencode(qsearch), headers={'Cookie': 'uvkey=%s' % qsearch['uk']})
        page = HTML.ElementFromString(qsearch2['RESULT'])
        lis.extend(page.xpath('.//li'))
        if qsearch2['RESULT_DATA']['isEnd']: 
          break
        qsearch.update(qsearch2['RESULT_DATA']['data']['qs-params'])

    for li in lis:
      try:
        spans = [s.strip() for s in li.xpath('.//div[@class="item-title"]/strong/*/span/text()')]
        if len(spans) == 2 and spans[1] == '역':
          role = spans[0]
          name = li.xpath('.//div[@class="item-contents"]/p/a | .//div[@class="item-contents"]/p/span')[0].text
          photo = li.xpath('.//div[@class="item-thumb"]//img/@data-original-src')[0]

          cast = dict()
          cast['name'] = name
          cast['role'] = role
          if photo != 'thumb_noimg':
            cast['photo'] = originalImageUrlFromCdnUrl(photo)
          roles.append(cast)
      except: Log.Debug(''.join(traceback.format_exc()))

    if roles:
      metadata.roles.clear()
      for role in roles:
        meta_role = metadata.roles.new()
        if 'role' in role:
          meta_role.role = role['role']
        if 'name' in role:
          meta_role.name = role['name']
        if 'photo' in role:
          meta_role.photo = role['photo']

  # TV검색 > 정보 > 사이트 > 공식홈
  home = html.xpath(u'//dt[.="사이트"]/following-sibling::dd//a[.="공식홈"]/@href')
  if home:
    if 'imbc.com' in home[0]:
      # 프로그램 홈
      # https://program.imbc.com/mydearest
      # https://program.imbc.com/MotelCalifornia
      page = HTTP.Request(home[0]).content
      bid = Regex(r'var bid = (\d+)').search(page).group(1)

      # https://control.imbc.com/Progarm/Menu?callback=ProgramSetMenu_1006641100000100000_P&bid=1006641100000100000&device=P
      # https://control.imbc.com/Progarm/Menu?bid=1006641100000100000&device=P
      res = JSON.ObjectFromURL('https://control.imbc.com/Progarm/Menu?bid=%s&device=P' % bid)
      try:
        poster_menu = (m for m in res['List'] if m['Menuname1'] == '포스터').next()
        # Log(poster_menu['Keyword'])
        for pg in range(10):
          page = HTML.ElementFromURL('https://imbbs.imbc.com/v2/list.aspx?bid=%s&page=%s&list_use=1&sk=&sv=' % (poster_menu['Keyword'], pg + 1))
          # Paging(15, 2, 12, 10, 1, "")
          # Paging(15, 2, 12, 10, 2, "")
          imgs = page.xpath('//table[@class="board_table type_photo"]//img/@src')
          if not imgs:
            break
          for img in [ 'https:' + img if img.startswith('//') else img for img in imgs ]:
            if img not in metadata.posters:
              try:
                metadata.posters[img] = Proxy.Preview(HTTP.Request(img, headers={ 'Accept': 'image/jpeg' }, cacheTime=0), sort_order=len(metadata.posters) + 1)
              except: pass
      except StopIteration:
        Log.Debug('No poster menu')

  # for s in media.seasons:
  #   Log('media    S%s: %s' % ( s, ' '.join('E' + e for e in media.seasons[s].episodes )))
  # for s in metadata.seasons:
  #   Log('metadata S%s: %s' % ( s, ' '.join('E' + e for e in metadata.seasons[s].episodes )))

  # TV검색 > 정보 > 사이트 > 다시보기
  vod = html.xpath(u'//dt[.="사이트"]/following-sibling::dd//a[.="다시보기"]/@href')

  replay_url = ''
  replay_extracted = False

  if vod:
    replay_url = vod[0]
  else:
    if home and 'program.kbs.co.kr' in home[0]:
      # 카카오VOD > http://program.kbs.co.kr/2tv/drama/dramaspecial2018/pc/list.html?smenu=c2cc5a
      replay_url = home[0] + 'list.html?smenu=c2cc5a'
    elif home and 'disneyplus.com' in home[0]:
      # https://www.disneyplus.com/ko-kr/browse/entity-7d607023-2f51-40f8-9316-b554b7a05c41
      replay_url = home[0]
    else:
      if metadata.studio and Regex('MBC|SBS|KBS|EBS').match(metadata.studio):
        Log.Debug('No replay URL for [%s] %s' % (metadata.studio, metadata.title))

  if replay_url:
    Log('%s: %s %s' % (metadata.studio, media.title, replay_url))
    if 'imbc.com' in replay_url:
      try:
        # http://www.imbc.com/broad/tv/drama/forensic/vod/
        if 'www.imbc.com' in replay_url:
          page = HTML.ElementFromURL(replay_url)
          bid = Regex('var progCode = "(\d+)";').search(page.xpath('//script[contains(.,"var progCode = ")]/text()')[0]).group(1)
        elif 'playvod.imbc.com/Vod/' in replay_url:
          # http://playvod.imbc.com/Vod/VodPlay?broadcastId=1005032100002100000 (ContentId)
          page = HTML.ElementFromURL(replay_url)
          bid = Regex('var programId = "(\d+)";').search(page.xpath('//script[contains(.,"var programId = ")]/text()')[0]).group(1)
        elif 'playvod.imbc.com/templete/' in replay_url:
          # https://playvod.imbc.com/templete/VodList?bid=1006311100000100000   (ProgramId)
          bid = Regex('bid=(\d+)').search(replay_url).group(1)
        else:
          raise Exception('no BID')

        for page in range(1, 11):
          # https://playvod.imbc.com/api/ContentList_Templete?programId=1006311100000100000&orderBy=d&selectYear=0&curPage=1&pageSize=8&_=1707915741915
          res = JSON.ObjectFromURL('https://playvod.imbc.com/api/ContentList_Templete?programId=%s&orderBy=d&selectYear=0&curPage=%d&pageSize=%d&_=%d'
            % ( bid, page, 100, time.time() ), sleep=0.5)
          # if len(res['ContList']) == 0:
          #   Log.Debug('*** no ContList')
          for cont in res['ContList']:
            # Log('E%s %s %s %s' % (cont['ContentNumber'], cont['BroadDate'], cont['ContentTitle'], cont['Preview']))
            episode_date = Datetime.ParseDate(cont['BroadDate']).date() # 2018-07-17
            episode_num = cont['ContentNumber']
            date_based_season_num = episode_date.year
            date_based_episode_num = episode_date.strftime('%Y-%m-%d')

            match = Regex(u'^(\d+(-\d+)?)$').search(episode_num)  # 1, 7-8, 특집
            if match:
              # if '-' in match.group(1):
              #   Log.Debug('*** %s' % episode_num)
              for episode_num in match.group(1).split('-'):
                episode = (metadata_for('1', episode_num)
                        or metadata_for(date_based_season_num, date_based_episode_num))
                if episode:
                  episode.summary = String.DecodeHTMLEntities(String.StripTags(cont['Preview'])).strip()
                  episode.originally_available_at = episode_date
                  episode.title = String.DecodeHTMLEntities(cont['ContentTitle']).strip()
                  episode.rating = None
                  try:
                    if Prefs['use_episode_thumbnail'] and cont['ContentImg'] not in episode.thumbs:
                      episode.thumbs[cont['ContentImg']] = Proxy.Preview(HTTP.Request(cont['ContentImg'], cacheTime=0, sleep=0.5))
                  except: pass
            else:
              # Log.Debug('*** %s' % episode_num)
              episode = metadata_for(date_based_season_num, date_based_episode_num)
              if episode:
                episode.summary = String.DecodeHTMLEntities(String.StripTags(cont['Preview'])).strip()
                episode.originally_available_at = episode_date
                episode.title = String.DecodeHTMLEntities(cont['ContentTitle']).strip()
                episode.rating = None
                try:
                  if Prefs['use_episode_thumbnail'] and cont['ContentImg'] not in episode.thumbs:
                    episode.thumbs[cont['ContentImg']] = Proxy.Preview(HTTP.Request(cont['ContentImg'], cacheTime=0, sleep=0.5))
                except: pass

          if len(res['ContList']) < 100: break

        replay_extracted = True
      except Exception as e:
        Log.Debug(repr(e))
        pass

    elif 'sbs.co.kr' in replay_url:
      try:
        if metadata.studio != 'SBS':
          raise Exception('studio mismatch')

        if 'allvod.sbs.co.kr/search' in replay_url:
          # (3) https://allvod.sbs.co.kr/search/22000010906/22000291095?type=program&time=30 (무료보기)
          media_id = Regex('search/(\d+)/(\d+)').search(replay_url).group(2)
          res = JSON.ObjectFromURL('https://static.apis.sbs.co.kr/allvod-api/media_sub/header/%s?type=program&jwt-token=' % media_id)
          replay_url = res['content']['hom_url'] # http://programs.sbs.co.kr/drama/30but17

        elif 'allvod.sbs.co.kr/allvod' in replay_url:
          # (2) http://allvod.sbs.co.kr/allvod/vodFreeProgramDetail.do?type=legend&pgmId=00000263249  # 발리에서 생긴일
          program_id = Regex('pgmId=(\d+)').search(replay_url).group(1)
          # https://static.apis.sbs.co.kr/allvod-api/media_sub/vod/00000263249?jwt-token=&page=1&sort=&free_yn=N&srs_id=&srs_year=
          res = JSON.ObjectFromURL('https://static.apis.sbs.co.kr/allvod-api/media_sub/vod/%s?jwt-token=&page=1&sort=&free_yn=N&srs_id=&srs_year=' % program_id)
          media_id = res['media']['items'][0]['mda_id']['items'][0]['id']
          res = JSON.ObjectFromURL('https://static.apis.sbs.co.kr/allvod-api/media_sub/header/%s?type=program&jwt-token=' % media_id)
          replay_url = res['content']['hom_url'] # http://programs.sbs.co.kr/drama/bali

        if 'programs.sbs.co.kr' not in replay_url:
          raise Exception('invalid replay_url')

        # (1) http://programs.sbs.co.kr/enter/jungle/vods/50479
        program_cd = Regex('programs\.sbs\.co\.kr/(.+?)/([^/]+)').search(replay_url).group(2)

        # http://static.apis.sbs.co.kr/program-api/1.0/menu/jungle
        menu = JSON.ObjectFromURL('http://static.apis.sbs.co.kr/program-api/1.0/menu/%s' % program_cd)

        shareimg = menu['program']['shareimg'].replace('_w640_h360', '_ori')
        if shareimg.startswith('//'):
          shareimg = 'http:' + shareimg
        if shareimg not in metadata.art:
          try:
            metadata.art[shareimg] = Proxy.Preview(HTTP.Request(shareimg, cacheTime=0), sort_order=len(metadata.art) + 1)
          except: pass

        # http://static.apis.sbs.co.kr/play-api/1.0/sbs_vodalls?...
        vods = JSON.ObjectFromURL('http://static.apis.sbs.co.kr/play-api/1.0/sbs_vodalls?offset=%d&limit=%d&sort=new&search=&cliptype=&subcategory=&programid=%s&absolute_show=Y&mdadiv=01&viewcount=Y' %
            ( 0, 2000, menu['program']['fullprogramid'] ), max_size=JSON_MAX_SIZE)
        # if len(vods['list']) == 0:
        #   Log.Debug('*** no vods')  # 더솔져스
        for v in vods['list']:
          # Log('%s %s-%s %s, %s...' % (v['broaddate'], v['content']['contentnumber'], v['content']['cornerid'], v['content']['contenttitle'], v['synopsis'][:20] ))

          # 2018-01-25T23:10:00.000Z 2-0 김어준의 블랙하우스 2회, 프롤로그<br>
          # 2018-01-18T23:10:00.000Z 1-3 김어준의 블랙하우스 정규 1회, 독한 대담ㅣ양정철 납치작전<br>
          # 2017-11-05T23:05:00.000Z 1-2 김어준의 블랙하우스 파일럿 2회,  김어준의 블랙하우스 파일럿 2회...
          # 2017-11-04T23:15:00.000Z 1-1 김어준의 블랙하우스 파일럿 1회,  김어준의 블랙하우스 파일럿 1회...

          # 2019-05-09T22:00:00.000Z 4-2 녹두꽃 1-8회 감독판-사람,하늘이 되다, [3&4회차 통합본] ※ 본 회차는 ...
          # 2019-05-08T22:00:00.000Z 4-1 녹두꽃 1-8회 감독판-사람,하늘이 되다, [1&2회차 통합본] ※ 본 회차는 ...
          # 2019-05-04T22:00:00.000Z 4-0 “문명이 사람 교화시킬 것”, [7&8회차 통합본] 이방을 하지 않...
          # 2019-05-03T22:00:00.000Z 3-0 “안허겄다구요 이방”, [5&6회차 통합본] 횃불이 휩쓸고 ...
          # 2019-04-27T22:00:00.000Z 2-0 “수금이나 하러 갈까나”, [3&4회차 통합본] 마침내 고부를 ...
          # 2019-04-26T22:00:00.000Z 1-0 “백성에겐 쌀을 탐관오리에겐 죽음을”, [1&2회차 통합본] 절망의 땅 18...

          # 2016-12-05T22:00:00.000Z 9-0 선(善)의 경계, 도원장은 서정이 PTSD 임을 알고도...
          # 2016-11-29T22:00:00.000Z 8-2 휴머니즘의 발로(發路), 서정의 목에 낫을 갖다대며 수술을 중...
          # 2016-11-29T20:55:00.000Z 8-1 낭만닥터 김사부 스페셜, 스페셜 | 낭만닥터 김사부 모아보기<...
          # 2016-11-28T22:00:00.000Z 7-0 불안 요소, 현철은 기태에게 ‘행정 실장’ 발령장...

          # 2017-11-28T22:00:00.000Z 3-0 “이거 안 놔?”, 종삼(윤균상)은 교도소를 눈 앞에 두...
          # 2017-11-27T22:35:00.000Z 2-0 “나갈 거야. 탈옥한다고”, 형수 김종삼(윤균상), 오일승 순경 ...
          # 2017-11-27T22:00:00.000Z 1-2 “착하게 살려고 했는데...”, 사형수 김종삼(윤균상), 오일승 순경...
          # 2017-11-25T16:25:00.000Z 1-1 의문의 일승 미리보기, <b><font color="red"...

          episode_date = Datetime.ParseDate(v['broaddate']).date()   # 2021-05-29T20:55:00.000Z # Fix TZ
          date_based_season_num = episode_date.year
          date_based_episode_num = episode_date.strftime('%Y-%m-%d')

          if Regex('(특집|스페셜|감독판|미리보기|파일럿|숨겨진 이야기|끝나지 않은 이야기|은밀한 이야기)').match(v['content']['contenttitle']):
            episode = metadata_for(date_based_season_num, date_based_episode_num)
            if episode:
              episode.summary = String.DecodeHTMLEntities(v['synopsis']).strip()
              episode.originally_available_at = episode_date
              episode.title = String.DecodeHTMLEntities(v['content']['contenttitle']).strip()  # '&lt;무영검&gt; 이서진씨와 함께...'
              episode.rating = None
              try:
                if Prefs['use_episode_thumbnail'] and v['thumb']['medium'] not in episode.thumbs:
                  episode.thumbs[v['thumb']['medium']] = Proxy.Preview(HTTP.Request(v['thumb']['medium'], cacheTime=0, sleep=0.5))
              except: pass
          else:
            episode_nums = []
            match = Regex(u'^\[(\d+)&(\d+)회차 통합본\]').search(v['synopsis'])
            if match:
              episode_nums.append(match.group(1))
              episode_nums.append(match.group(2))
            else:
              episode_nums.append(str(v['content']['contentnumber']))
            for episode_num in episode_nums:
              episode = (metadata_for('1', episode_num)
                      or metadata_for(date_based_season_num, date_based_episode_num))
              if episode:
                episode.summary = String.DecodeHTMLEntities(v['synopsis']).strip()
                episode.originally_available_at = episode_date
                episode.title = String.DecodeHTMLEntities(v['content']['contenttitle']).strip()  # '&lt;무영검&gt; 이서진씨와 함께...'
                episode.rating = None
                try:
                  if Prefs['use_episode_thumbnail'] and v['thumb']['medium'] not in episode.thumbs:
                    episode.thumbs[v['thumb']['medium']] = Proxy.Preview(HTTP.Request(v['thumb']['medium'], cacheTime=0, sleep=0.5))
                except: pass

        replay_extracted = True
      except Exception as e:
        Log.Debug(repr(e))
        pass

    elif 'program.kbs.co.kr' in replay_url:
      try:
        # http://program.kbs.co.kr/2tv/enter/gagcon/pc/list.html?smenu=c2cc5a
        source, sname, stype, smenu = Regex('program.kbs.co.kr/(.+?)/(.+?)/(.+?)/pc/list.html\?smenu=(.+)$').search(replay_url).group(1, 2, 3, 4)

        # http://pprogramapi.kbs.co.kr/api/v1/page?platform=P&smenu=c2cc5a&source=2tv&sname=enter&stype=gagcon&page_type=list
        menu = JSON.ObjectFromURL('http://pprogramapi.kbs.co.kr/api/v1/page?platform=P&smenu=%s&source=%s&sname=%s&stype=%s&page_type=list' %
            ( smenu, source, sname, stype ))

        image_h = menu['data']['site']['meta']['image_h']
        if image_h and image_h not in metadata.posters:
          try:
            metadata.posters[image_h] = Proxy.Preview(HTTP.Request(image_h, cacheTime=0), sort_order=len(metadata.posters) + 1)
          except: pass

        image_w = menu['data']['site']['meta']['image_w']
        if image_w and image_w not in metadata.art:
          try:
            metadata.art[image_w] = Proxy.Preview(HTTP.Request(image_w, cacheTime=0), sort_order=len(metadata.art) + 1)
          except: pass

        page = 1
        while True:
          # https://static.api.kbs.co.kr/mediafactory/v1/contents?rtype=jsonp&sort_option=program_planned_date%7Cdesc&program_code=T2017-0270&descriptive_video_service_yn=N&page=1&page_size=9&&callback=angular.callbacks._0
          res = JSON.ObjectFromURL('https://static.api.kbs.co.kr/mediafactory/v1/contents?rtype=json&sort_option=%s&program_code=%s&descriptive_video_service_yn=N&page=%d&page_size=%d'
            % ( 'program_planned_date%7Cdesc', menu['data']['site']['meta']['program_code'], page, 18 ), sleep=0.5)

          if 'error_msg' in res:
            Log.Debug(res['error_msg'])
            break

          for v in res['data']:
            # Log('%s %s %s' % (v['program_planned_date'], v['program_sequence_number'], v['program_subtitle']))
            episode_date = Datetime.ParseDate(v['program_planned_date']).date() # 20130825
            date_based_season_num = episode_date.year
            date_based_episode_num = episode_date.strftime('%Y-%m-%d')
            if v['program_sequence_number']:
              episode_num = str(v['program_sequence_number'])
              episode = (metadata_for('1', episode_num)
                      or metadata_for(date_based_season_num, date_based_episode_num))
            else:
              # Log.Debug('*** no sequence number')
              episode = metadata_for(date_based_season_num, date_based_episode_num)
            if episode:
              episode.summary = v['main_story']
              episode.originally_available_at = episode_date
              episode.title = v['program_subtitle'] or date_based_episode_num
              episode.rating = None     # float(v['avg_rating'])
              try:
                if Prefs['use_episode_thumbnail'] and v['image_w'] not in episode.thumbs:
                  episode.thumbs[v['image_w']] = Proxy.Preview(HTTP.Request(v['image_w'], cacheTime=0, sleep=0.5))
              except: pass

          page += 1
          if page > res['page_count']:
            break

        replay_extracted = True
      except Exception as e:
        Log.Debug(repr(e))
        pass

    elif 'home.ebs.co.kr' in replay_url:
      try:
        if '/replay/' not in replay_url:
          try:
            # http://home.ebs.co.kr/bestdoctors/review (명의 헬스케어)
            res = HTTP.Request(replay_url.replace('http:', 'https:'), follow_redirects=False).content
          except RedirectError as e:
            # => https://home.ebs.co.kr/bestdoctors/replay/1/list?courseId=BP0PAPG0000000014&stepId=01BP0PAPG0000000014
            replay_url = e.headers['location']

        courseId, stepId = Regex('courseId=(.+)&stepId=(.+)').search(replay_url).group(1, 2)
        for page in range(1, 41):
          # https://www.ebs.co.kr/tv/show?courseId=BP0PAPG0000000014&stepId=01BP0PAPG0000000014 # 명의 헬스케어
          # https://www.ebs.co.kr/tv/show?courseId=10016245&stepId=10035139&lectId=60444302 # 세상에 나쁜 개는 없다 시즌3
          res = HTML.ElementFromURL('https://www.ebs.co.kr/tv/show/vodListNew', values={
              'courseId': courseId,
              'stepId': stepId,
              'lectId': '666',    # '10962899',
              'vodStepNm': '',    # '세상에 나쁜 개는 없다 시즌3',
              # 'srchType': '',
              # 'srchText': '',
              # 'srchYear': '',
              # 'srchMonth': '',
              'pageNum': page,
              # 'vodProdId': ''
          }, sleep=0.5)
          for a in res.xpath('//ul[@class="_playList"]/li//a'):
            episode_date = Datetime.ParseDate(a.xpath('./span[@class="date"]')[0].text).date()  # 2024.02.17
            date_based_season_num = episode_date.year
            date_based_episode_num = episode_date.strftime('%Y-%m-%d')
            match = Regex(u'^(\d+)회').search(a.text.strip())
            if match:
              episode_num = match.group(1)
              episode = (metadata_for('1', episode_num)
                      or metadata_for(date_based_season_num, date_based_episode_num))
            else:
              episode = metadata_for(date_based_season_num, date_based_episode_num)
            if episode:
              # if episode.summary and u'회차정보가 없습니다' not in episode.summary:
              #   continue
              # Log('E: S%s E%s %s %s' % (season_num, episode_num, episode_date, a.text.strip()))
              show = HTML.ElementFromURL('https://www.ebs.co.kr/tv/show?prodId=&lectId=%s' % Regex('selVodList\(\'(\d+?)\'').search(a.get('href')).group(1), sleep=0.5)
              episode.summary = (show.xpath('//p[@class="detail_story"]') or      # https://www.ebs.co.kr/tv/show?... (극한직업)
                                 show.xpath('//div[@class="detail-page__text"]')  # https://bestdoctors.ebs.co.kr/bestdoctors/vodReplayView?...
                                )[0].text.strip()
              episode.originally_available_at = episode_date
              episode.title = a.text.strip() or date_based_episode_num
              episode.rating = None

          if page >= int(''.join(res.xpath('//span[@class="pro_vod_page"]//text()')).strip().split(' / ')[1]):
            break

        # url = replay_url
        # for page in range(1, 51):
        #   # https://home.ebs.co.kr/bestdoctors/replay/1/list?courseId=BP0PAPG0000000014&stepId=01BP0PAPG0000000014 (명의)
        #   res = HTML.ElementFromURL(url, sleep=0.5)
        #   for div in res.xpath('//div[@class="half-list__item"]'):
        #     title = div.xpath('.//div[@class="half-list__title"]/text()')[0]
        #     episode_date = Datetime.ParseDate(div.xpath('.//div[@class="half-list__date"]/text()')[0]).date() # 2024.02.16
        #     date_based_season_num = episode_date.year
        #     date_based_episode_num = episode_date.strftime('%Y-%m-%d')
        #     match = Regex(u'^(\d+)회').search(title)
        #     if match:
        #       episode_num = match.group(1)
        #       episode = (metadata_for('1', episode_num)
        #               or metadata_for(date_based_season_num, date_based_episode_num))
        #     else:
        #       episode = metadata_for(date_based_season_num, date_based_episode_num)
        #     if episode:
        #       # if episode.summary and u'회차정보가 없습니다' not in episode.summary:
        #       #   continue
        #       # /bestdoctors/vodReplayView?pageNm=replay&siteCd=ME&courseId=BP0PAPG0000000014&stepId=01BP0PAPG0000000014&lectId=60444293
        #       show = HTML.ElementFromURL(urlparse.urljoin(url, div.xpath('a/@href')[0]), sleep=0.5)
        #       episode.summary = show.xpath('//div[@class="detail-page__text"]')[0].text.strip()
        #       episode.originally_available_at = episode_date
        #       episode.title = title
        #       episode.rating = None
        #       try:
        #         thumb = div.xpath('a/div/img/@src')[0]
        #         if Prefs['use_episode_thumbnail'] and thumb not in episode.thumbs:
        #           episode.thumbs[thumb] = Proxy.Preview(HTTP.Request(thumb, cacheTime=0, sleep=0.5))
        #       except: pass
        #   nexta = res.xpath('//div[@class="pagination__number-area"]/strong/following-sibling::a[1]/@href | //button[contains(@class,"pagination__arrow--next")]/@onclick')
        #   if not nexta:
        #     break
        #   url = urlparse.urljoin(url, re.sub('(^location.href=\')?(.*?)(\')?$', '\\2', nexta[0]))

        # url = replay_url
        # for page in range(1, 51):
        #   # http://home.ebs.co.kr/limit/replay/2/list?courseId=BP0PHPN0000000006&stepId=01BP0PHPN0000000006 (극한직업)
        #   res = HTML.ElementFromURL(url, follow_redirects=True, sleep=0.5)
        #   for li in res.xpath('//ul[@class="lst_pro02"]/li'):
        #     a = li.xpath('p[@class="thum"]/a')[0]
        #     title = ''.join(li.xpath('.//span[@class="stit_info"]/text()')).strip()
        #     episode_date = Datetime.ParseDate(li.xpath('.//span[@class="date_info"]')[0].text).date()  # 2024.02.17
        #     date_based_season_num = episode_date.year
        #     date_based_episode_num = episode_date.strftime('%Y-%m-%d')
        #     match = Regex(u'^(\d+)회').search(title)
        #     if match:
        #       episode_num = match.group(1)
        #       episode = (metadata_for('1', episode_num)
        #               or metadata_for(date_based_season_num, date_based_episode_num))
        #     else:
        #       episode = metadata_for(date_based_season_num, date_based_episode_num)
        #     if episode:
        #       # if episode.summary and u'회차정보가 없습니다' not in episode.summary:
        #       #   continue
        #       # https://www.ebs.co.kr/tv/show?prodId=567&lectId=60444644
        #       show = HTML.ElementFromURL('https://www.ebs.co.kr/tv/show?prodId=&lectId=%s' % Regex('fn_view\(\'(\d+)\'').search(a.get('onclick')).group(1), sleep=0.5)
        #       episode.summary = show.xpath('//p[@class="detail_story"]')[0].text.strip()
        #       episode.originally_available_at = episode_date
        #       episode.title = title
        #       episode.rating = None
        #       try:
        #         thumb = a.xpath('img/@src')[0]
        #         if Prefs['use_episode_thumbnail'] and thumb not in episode.thumbs:
        #           episode.thumbs[thumb] = Proxy.Preview(HTTP.Request(thumb, cacheTime=0, sleep=0.5))
        #       except: pass
        #   nexta = res.xpath('//span[@class="num"]/a[@class="on"]/following-sibling::a[1] | //a[@class="page_next"]')
        #   if not nexta:
        #     break
        #   url = urlparse.urljoin(url, nexta[0].get('href'))

        replay_extracted = True
      except:
        Log.Debug(''.join(traceback.format_exc()))
        pass

    elif 'www.tving.com' in replay_url:
      try:
        # https://www.tving.com/contents/P001751069
        # https://www.tving.com/vod/player/E003636825
        program_code = Regex('/([A-Z]\d+)$').search(replay_url).group(1)
        if program_code.startswith('E'):
          res = JSON.ObjectFromURL('https://api.tving.com/v2/media/content/info?mediaCode=%s&screenCode=CSSD0100&networkCode=CSND0900&osCode=CSOD0900&teleCode=CSCD0900&apiKey=%s'
              % ( program_code, '1e7952d0917d6aab1f0293a063697610' ))
          program_code = res['body']['content']['program_code']

        res = JSON.ObjectFromURL(('https://api.tving.com/v2/media/frequency/program/%s?'
            'order=new&screenCode=CSSD0100&networkCode=CSND0900&osCode=CSOD0900&teleCode=CSCD0900&apiKey=%s&'
            'cacheType=main&pageSize=20&&adult=all&free=all&guest=all&scope=all') % ( program_code, '1e7952d0917d6aab1f0293a063697610' ))

        for result in res['body']['result']:
          episode_date = Datetime.ParseDate(str(result['episode']['broadcast_date'])).date()
          episode_num = str(result['episode']['frequency'])
          episode = metadata_for('1', episode_num)
          if episode:
            episode.summary = result['episode']['synopsis']['ko']
            episode.originally_available_at = episode_date
            episode.title = result['vod_name']['ko']
            episode.rating = None
            try:
              # https://image.tving.com/upload/cms/caie/CAIE0200/E000920697.jpg
              thumb = 'https://image.tving.com' + result['episode']['image'][0]['url']
              if Prefs['use_episode_thumbnail'] and thumb not in episode.thumbs:
                episode.thumbs[thumb] = Proxy.Preview(HTTP.Request(thumb, cacheTime=0, sleep=0.5))
            except: pass

        replay_extracted = True
      except:
        Log.Debug(''.join(traceback.format_exc()))

    elif 'disneyplus.com' in replay_url:
      try:
        if '/browse/' not in replay_url:
          try:
            # https://www.disneyplus.com/ko-kr/series/a-shop-for-killers/6pcuvK0SUuHI
            res = HTTP.Request(replay_url, follow_redirects=False).content
          except Ex.HTTPError as e:
            if e.code == 308: # Permanent Redirect
              # => /ko-kr/browse/entity-7d607023-2f51-40f8-9316-b554b7a05c41
              replay_url = urlparse.urljoin(replay_url, e.headers['location'])
            else:
              raise

        # https://www.disneyplus.com/ko-kr/browse/entity-7d607023-2f51-40f8-9316-b554b7a05c41
        page = HTML.ElementFromURL(replay_url)

        match = Regex(u'시즌 ?(\d+)$').search(metadata.title)
        season_num_expected = match.group(1) if match else '1'
        
        opt = page.xpath(u'//select[@id="season"]/option[text()="시즌 %s"]' % season_num_expected)[0]
        if opt.get('selected') == None:
          replay_url = urlparse.urljoin(replay_url, '?season=%s' % opt.get('value'))
          page = HTML.ElementFromURL(replay_url)

        for li in page.xpath('//section[@data-testid="episodesContent"]//li'):
          try:
            p = li.xpath('.//div[@data-testid="image-card-metadata"]/p')
            season_num, episode_num, episode_title = Regex(u'시즌 (\d+): (\d+)회 (.*)').search(p[0].text).group(1, 2, 3)
            # Log.Debug('S{} E{} {}, {}'.format(season_num, episode_num, episode_title, p[1].text))

            episode = metadata.seasons['1'].episodes[episode_num]
            episode.summary = p[1].text
            episode.originally_available_at = metadata.originally_available_at
            episode.title = episode_title
            episode.rating = None

            thumb = li.xpath('.//picture/source[1]/@srcset')[0].split(' ', 1)[0]
            if Prefs['use_episode_thumbnail'] and thumb not in episode.thumbs:
              episode.thumbs[thumb] = Proxy.Preview(HTTP.Request(thumb, cacheTime=0, sleep=0.5))
          except: pass

        replay_extracted = True
      except:
        Log.Debug(''.join(traceback.format_exc()))

    else:
      Log.Debug('*** 다시보기 not handled: %s' % replay_url)

#   # (4) from episode page
#   for a in html.xpath('//ul[@id="clipDateList"]/li/a'):
#     try:
#       episode_date = Datetime.ParseDate(a.xpath('./parent::li/@data-clip')[0]).date()
#     except: continue
#     date_based_season_num = episode_date.year
#     date_based_episode_num = episode_date.strftime('%Y-%m-%d')
#     episode_num = a.xpath(u'substring-before(./span[@class="txt_episode"],"회")')
#     if episode_num:
#       episode = (metadata_for('1', episode_num)
#               or metadata_for(date_based_season_num, date_based_episode_num))
#     else: # 응답하라 1988: 시청지도서
#       episode = metadata_for(date_based_season_num, date_based_episode_num)
#     if episode:
#       if episode.summary and (u'회차정보가 없습니다' not in episode.summary) and (u'줄거리 정보 준비 중입니다' not in episode.summary):
#         continue
#       page = HTML.ElementFromURL('https://search.daum.net/search' + a.get('href'), sleep=0.5)
#       subtitle = page.xpath('//p[@class="episode_desc"]/strong/text()')
#       episode.summary = '\n'.join(txt.strip() for txt in page.xpath('//p[@class="episode_desc"]/text()')).strip()
#       episode.originally_available_at = episode_date
#       episode.title = subtitle[0] if subtitle else date_based_episode_num
#       episode.rating = None
#
#       if directors:
#         episode.directors.clear()
#         for director in directors:
#           meta_director = episode.directors.new()
#           if 'name' in director:
#             meta_director.name = director['name']
#           if 'photo' in director:
#             meta_director.photo = director['photo']
#       if writers:
#         episode.writers.clear()
#         for writer in writers:
#           meta_writer = episode.writers.new()
#           if 'name' in writer:
#             meta_writer.name = writer['name']
#           if 'photo' in writer:
#             meta_writer.photo = writer['photo']

  # TV검색 > 회차
  if not replay_extracted:
    episode_href = html.xpath(u'//div[@class="c-section-tab"]//li/a[.="회차"]/@href')
    for c in range(100):
      if not episode_href:
        break

      page = HTML.ElementFromURL('https://search.daum.net/search%s' % episode_href[0], sleep=0.5)
      try:
        # 2023.08.04.금
        episode_date = Datetime.ParseDate(page.xpath(u'//span[text()="방영일"]/following-sibling::text()')[0][0:-1]).date()
      except: break
      date_based_season_num = episode_date.year
      date_based_episode_num = episode_date.strftime('%Y-%m-%d')
      episode_num = page.xpath(u'substring-before(//option[@selected]/@value,"회")')
      episode_title = page.xpath('//strong[@class="tit_story"]/text()')
      if episode_num:
        episode = (metadata_for('1', episode_num)
                or metadata_for(date_based_season_num, date_based_episode_num))
      else: # 응답하라 1988: 시청지도서
        episode = metadata_for(date_based_season_num, date_based_episode_num)
      if episode:
        episode.summary = page.xpath('//p[@class="desc_story"]/text()')[0]
        episode.originally_available_at = episode_date
        episode.title = episode_title[0] if episode_title else date_based_episode_num
        episode.rating = None
        episode_set_directors(episode, directors)
        episode_set_writers(episode, writers)

      episode_href = page.xpath(u'//div[@class="paging"]/a[span[.="이전 회차"]]/@href')

  #   # (5) fill missing info
  #   # if Prefs['override_tv_id'] != 'None':
  #   #   page = HTTP.Request(DAUM_TV_DETAIL2 % metadata.id).content
  #   #   match = Regex('<em class="title_AKA"> *<span class="eng">([^<]*)</span>').search(page)
  #   #   if match:
  #   #     metadata.original_title = match.group(1).strip()

####################################################################################################
class DaumMovieAgent(Agent.Movies):
  name = "Daum Movie"
  languages = [Locale.Language.Korean]
  primary_provider = True
  accepts_from = ['com.plexapp.agents.localmedia']

  def search(self, results, media, lang, manual=False):
    return searchDaumMovie(results, media, lang)

  def update(self, metadata, media, lang):
    Log.Info("in update ID = %s" % metadata.id)
    updateDaumMovie(metadata, media)

    # override metadata ID
    if Prefs['override_movie_id'] != 'None':
      title = metadata.original_title if metadata.original_title else metadata.title
      if Prefs['override_movie_id'] == 'IMDB':
        url = IMDB_TITLE_SRCH % urllib.quote_plus("%s %d" % (title.encode('utf-8'), metadata.year))
        page = HTTP.Request( url ).content
        match = RE_IMDB_ID.search(page)
        if match:
          metadata.id = match.group(1)
          Log.Info("override with IMDB ID, %s" % metadata.id)

class DaumMovieTvAgent(Agent.TV_Shows):
  name = "Daum Movie"
  primary_provider = True
  languages = [Locale.Language.Korean]
  accepts_from = ['com.plexapp.agents.localmedia']

  def search(self, results, media, lang, manual=False):
    return searchDaumTV(results, media, lang)

  def update(self, metadata, media, lang):
    Log.Info("in update ID = %s" % metadata.id)
    updateDaumTV(metadata, media)

    # override metadata ID
    if Prefs['override_tv_id'] != 'None':
      title = metadata.original_title if metadata.original_title else metadata.title
      if Prefs['override_tv_id'] == 'TVDB':
        url = TVDB_TITLE_SRCH % urllib.quote_plus(title.encode('utf-8'))
        xml = XML.ElementFromURL( url )
        node = xml.xpath('/Data/Series/seriesid')
        if node:
          metadata.id = node[0].text
          Log.Info("override with TVDB ID, %s" % metadata.id)
