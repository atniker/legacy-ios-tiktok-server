import json, base64, traceback, time, asyncio, threading, uuid, requests, datetime
from patchright.sync_api import sync_playwright, Playwright, Browser, Page, BrowserContext, Response
from google.protobuf import json_format, message

from AtnikFox import helpers
from AtnikFox.proto import directMessage

class TikTokScraper:
	def __init__(self, cookies):
		self.cookies = json.loads(base64.b64decode(cookies))
		self.BASE_URL = 'https://www.tiktok.com'
		self.LOGIN_SUCCESS_SELECTOR = 'div.tiktok-1of5hzw-DivProfileContainer' 
		self.SCROLL_PAUSE_TIME = 2
		self.queueThread = threading.Thread(target=self.executionQueue)
		self.queue = {}
		self.queueByTask = {}
		self.video_download_cookies = {}
		self.collected_videos = []
		self.die = False
		self.avaliable_packets = {
			'onDirectMessage': directMessage
		}

		self.player = None
		self.context = None
		self.page = None
		self.message_page = None
		self.username = None
		self.ms_token = None

		self.queueThread.start()

	def executionQueue(self):
		playwright_instance = sync_playwright().start()
		browser_instance = playwright_instance.chromium.launch(
			args=[
				# '--headless=new', 
				'--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-background-networking',
                '--disable-sync',
                '--blink-settings=imagesEnabled=false'
			], 
			headless=False,
			# proxy={'server': 'socks5://192.168.1.104:8080'}
		)

		self.context = browser_instance.new_context(
			user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
			viewport={"width": 800, "height": 600},
			no_viewport=True
		)

		self.context.route("**/*.{png,jpg,jpeg,gif,css,woff,woff2,ttf,mp4}", lambda route: route.abort())

		self.player = playwright_instance

		while True:
			try:
				time.sleep(0.3)

				if self.die:
					playwright_instance.stop()
					return

				if len(self.queue) < 1:
					continue

				result = None;success = True

				item_key = list(self.queue.keys())[0]
				item = self.queue[item_key]

				try:
					result = getattr(self, item['fun'])(*item['args']) if item['args'] != None else getattr(self, item['fun'])()
				except:
					traceback.print_exc()
					success = False

				self.queue[item_key]['result'] = {'ok': success, 'result': result}
			except:
				traceback.print_exc()
				time.sleep(1)

	async def executeQueued(self, fun, args=None):
		qid = str(uuid.uuid4())
		taskHash = f'{fun}{args}';initiator = True

		if taskHash in self.queueByTask:
			qid = self.queueByTask[taskHash]
			self.queue[qid]['awaiters'] += 1
			initiator = False

			print('sucking up the taskhash')
		else:
			self.queue[qid] = {'fun': fun, 'args': args, 'result': None, 'awaiters': 1}
			self.queueByTask[taskHash] = qid

		while self.queue[qid]['result'] == None:
			await asyncio.sleep(0.3)

		result = self.queue[qid]['result']
		self.queue[qid]['awaiters'] -= 1

		if initiator:
			while self.queue[qid]['awaiters'] > 0:
				time.sleep(0.3)

			del self.queue[qid]
			del self.queueByTask[taskHash]
			
			print('taskhash obliterated')

		if not result['ok']:
			raise Exception('queued task resulted in an error')

		return result['result']

	def loadCookies(self):
		try:
			sanitized_cookies = []
			valid_same_site_values = ['Strict', 'Lax', 'None']

			for cookie in self.cookies:
				if cookie['name'] == 'perf_feed_cache':
					continue

				print(cookie['name'])

				if cookie['name'] == 'msToken':
					self.ms_token = cookie['value']

				if cookie['name'] in ['msToken', 'tt_chain_token', 'tt_csrf_token', 'ttwid']:
					self.video_download_cookies[cookie['name']] = cookie['value']

				if 'sameSite' in cookie:
					if cookie['sameSite'] is None:
						cookie['sameSite'] = 'Lax'
					elif isinstance(cookie['sameSite'], str):
						normalized_same_site = cookie['sameSite'].capitalize()
						if normalized_same_site not in valid_same_site_values:
							cookie['sameSite'] = 'Lax'
						else:
							cookie['sameSite'] = normalized_same_site
					else:
						cookie['sameSite'] = 'Lax'
				else:
					cookie['sameSite'] = 'Lax'
				
				if cookie.get('secure') is False and cookie.get('sameSite') == 'None':
					cookie['secure'] = True
				if 'secure' not in cookie:
					cookie['secure'] = False
				
				sanitized_cookies.append(cookie)
			
			return sanitized_cookies
		except json.JSONDecodeError:
			return []
		except Exception:
			return []

	def login(self):
		cookies = self.loadCookies()
		if not cookies:
			return False

		try:
			self.context.add_cookies(cookies)
			self.page = self.context.new_page()
			
			self.page.goto(self.BASE_URL + '/foryou', wait_until="domcontentloaded", timeout=60000)
			self.page.on('response', self._harvestFypRequests)
			
			try:
				self.page.wait_for_selector(self.LOGIN_SUCCESS_SELECTOR, timeout=15000)
			except Exception:
				if "login" in self.page.url or "signup" in self.page.url:
					return False

			self.username = self.getSelf()
			self.initMessaging()
			return True

		except Exception:
			traceback.print_exc()

			return False

	def initMessaging(self):
		self.message_page = self.context.new_page()
		self._harvestWebsockets(self.message_page)

		self.message_page.goto(self.BASE_URL + '/messages?lang=en', wait_until="domcontentloaded", timeout=60000)

	def getNotifications(self):
		inbox = None;result = []

		try:
			inbox = self.page.locator('ul.css-1cz26jb-UlInboxItemListContainer')
		except:
			traceback.print_exc()

			notification_button_locator = self.page.locator('button[data-e2e="nav-activity"]').first

			if notification_button_locator.count() == 0:
				print('no button')
				return []

			notification_button_locator.click()
			time.sleep(1)

			inbox = self.page.locator('ul.css-1cz26jb-UlInboxItemListContainer')

		notifications = self.page.locator("div[data-e2e='inbox-list-item']").all()

		print(len(notifications))

		for i in range(len(notifications)):
			item = notifications[i]
			notification = {}

			title_element = item.locator("a[data-e2e='inbox-title']")
			notification['title'] = title_element.text_content(timeout=1000) if title_element.count() > 0 else None
			notification['profile_url'] = title_element.get_attribute('href', timeout=1000).split('@')[-1] if notification['title'] != None else None
			description_element = item.locator("p[data-e2e='inbox-content']")
			notification['description'] = description_element.text_content(timeout=1000) if description_element.count() > 0 else None
			avatar_element = item.locator('img[src^="https://p16-sign-va"]')
			notification['avatar'] = avatar_element.get_attribute('src', timeout=1000) if avatar_element.count() > 0 else None

			if notification['description'] == None or notification['title'] == None:
				print('important parameters missing')
				print(notification)
				continue

			result.append(notification)

		return result

	def getSelf(self):
		if not self.page:
			return None

		profile_link = None

		try:
			script_locator = self.page.locator('#__UNIVERSAL_DATA_FOR_REHYDRATION__')
			
			script_locator.wait_for(state='attached', timeout=15000)

			if not script_locator.count():
				raise Exception('no rehydration')

			profile_link = json.loads(script_locator.text_content(timeout=5000))['__DEFAULT_SCOPE__']['webapp.app-context']['user']['uniqueId']
		except Exception:
			traceback.print_exc()
		
		return profile_link

	def getTrending(self, min_amount):
		try:
			while len(self.collected_videos) < min_amount:
				max_index_value = self.page.evaluate('''() => {
					let maxIndex = -1;
					const articles = document.querySelectorAll('article[data-scroll-index]');
					articles.forEach(article => {
						const index = parseInt(article.getAttribute('data-scroll-index'));

						if (!isNaN(index) && index > maxIndex) {
							maxIndex = index;
						}
					});
					return maxIndex;
				}''')

				video_article_locator = self.page.locator(f'article[data-scroll-index="{max_index_value}"]').first
				
				try:
					video_article_locator.wait_for(state="attached", timeout=10000)
				except Exception:
					self.page.keyboard.down('PageDown')
					time.sleep(self.SCROLL_PAUSE_TIME)
					continue 

				try:
					video_article_locator.scroll_into_view_if_needed(timeout=5000)
				except Exception:
					self.page.keyboard.down('PageDown')
					time.sleep(self.SCROLL_PAUSE_TIME)
					continue
				
				self.page.keyboard.down('PageDown')
		except Exception:
			traceback.print_exc()
			

		result = self.collected_videos
		self.collected_videos = []
		
		return result

	def getProfile(self, username: str):
		result = None
		item_list_response = None;user_detail_response = None

		profile_url = f"https://www.tiktok.com/@{username}"
		profile_page = self.context.new_page()

		profile_page.goto(profile_url, wait_until="domcontentloaded", timeout=10000)

		try:
			with profile_page.expect_response(lambda r: 'https://www.tiktok.com/api/post/item_list' in r.url and r.status == 200, timeout=20000) as response_info:
				item_list_response = response_info.value.json()

			script_locator = profile_page.locator('#__UNIVERSAL_DATA_FOR_REHYDRATION__')

			if script_locator.count() < 0:
				raise Exception('no rehydration')

			user_detail_response = json.loads(script_locator.text_content(timeout=20000))['__DEFAULT_SCOPE__']['webapp.user-detail']

			data = user_detail_response

			author = data['userInfo']['user']
			authorStats = data['userInfo']['stats']

			result = {	
				'avatar_url': author['avatarThumb'],
				'name': author['nickname'],
				'username': author['uniqueId'],
				'description': 'no bio yet' if author['signature'] == '' else author['signature'],
				'following_count': helpers.makeNumber(authorStats['followingCount']),
				'followers_count': helpers.makeNumber(authorStats['followerCount']),
				'like_count': helpers.makeNumber(authorStats['heart']),
				'videos': [],
			}

			data = item_list_response

			if 'itemList' in data:
				if data['itemList'] != None:
					for i in data['itemList']:
						item = {
							'video_url': i['id'],
							'preview_url': i['video']['cover'],
							'view_count': helpers.makeNumber(i['stats']['playCount']),
							'is_pinned': (1 if i['isPinnedItem'] else 0) if 'isPinnedItem' in i else 0
						}

						result['videos'].append(item)
		except:
			traceback.print_exc()

		if profile_page:
			profile_page.close()

		return result

	def close(self):
		self.die = True

	def getComments(self, username: str, video_id: str):
		video_page = self.context.new_page()
		video_url = f"https://www.tiktok.com/@{username}/video/{video_id}"

		video_page.goto(video_url, wait_until="domcontentloaded", timeout=60000)

		try:
			with video_page.expect_response(lambda r: 'https://www.tiktok.com/api/comment/list' in r.url and r.status == 200, timeout=20000) as response_info:
				print(response_info.value.body())

				data = response_info.value.json()
				video_page.close()

				result = []

				for i in data['comments']:
					comment = {
						'author': {
							'username': i['user']['nickname'],
							'avatar_url': i['user']['avatar_thumb']['url_list'][-1],
							'profile_link': i['user']['unique_id']
						},
						'content': i['text'],
						'date': helpers.makeDate(i['create_time']),
						'likes': helpers.makeNumber(i['digg_count'])
					}

					if i['image_list'] != None:
						comment['content'] += ' [photo]'

					result.append(comment)

				return result
		except:
			traceback.print_exc()

		if video_page:
			video_page.close()

		return None

	def executeProtoEvents(self, message):
		result = None;event = None

		for i in self.avaliable_packets:
			try:
				try:
					decoded_bytes = base64.b64decode(message)
				except:
					break

				result = avaliable_packets[i]().ParseFromString(decoded_bytes)
				event = i

				break
			except:
				traceback.print_exc()

		if result == None:
			return

		result = json_format.MessageToJson(
			proto_message,
			including_default_value_fields=True,
			preserving_proto_field_name=True
		)

		getattr(self, event)(result)

	def onDirectMessage(self, data):
		data = data['field8']['field6']['field500']['field5']
		print(f'got message, \n{data}')

	def _harvestWebsockets(self, page):
		def on_websocket(websocket):
			def on_frame_received(frame):
				self.executeProtoEvents(frame.payload)

			def on_frame_sent(frame):
				print(f"WebSocket Sent: {frame.payload}")

			websocket.on("framereceived", on_frame_received)
			websocket.on("framesent", on_frame_sent)
			
		page.on("websocket", on_websocket)

	def _harvestFypRequests(self, response: Response):
		if response.status != 200:
			return

		if 'tiktok.com/api/recommend/item_list' in response.url:
			data = response.json()
			
			for i in data['itemList']:
				if 'video' not in i:
					continue

				result = {}

				result['comment_count'] = helpers.makeNumber(i['stats']['commentCount'])
				result['like_count'] = helpers.makeNumber(i['stats']['diggCount'])
				result['id'] = i['id']
				result['author_name'] = i['author']['uniqueId']
				result['author_avatar_url'] = i['author']['avatarThumb']

				try:
					for j in i['contents']:
						if 'desc' in j:
							result['description'] = j['desc']

							break
				except:
					result['description'] = ''

				try:
					result['video_url'] = i['video']['PlayAddrStruct']['UrlList'][0]
				except:
					traceback.print_exc()
					print('important parameters missing')

					continue

				self.collected_videos.append(helpers.makeVideo(result))

			print(str(len(self.collected_videos)) + ' videos total')

# def getVideo(username, video_id, ms_token):
# 	return pyktok.save_tiktok(f'https://www.tiktok.com/@{username}/video/{video_id}?is_copy_url=1&is_from_webapp=v1', True, ms_token=ms_token)



async def main():
	scraper = TikTokScraper(cookies='W3siZG9tYWluIjogIi53d3cudGlrdG9rLmNvbSIsICJleHBpcmF0aW9uRGF0ZSI6IDE3NjM3NjMyMTQsICJob3N0T25seSI6IGZhbHNlLCAiaHR0cE9ubHkiOiBmYWxzZSwgIm5hbWUiOiAiZGVsYXlfZ3Vlc3RfbW9kZV92aWQiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogbnVsbCwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogIjgifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzU3MzUyMTU5LjQ2MjMyMiwgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IGZhbHNlLCAibmFtZSI6ICJtc1Rva2VuIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6ICJub19yZXN0cmljdGlvbiIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJ3TlcwS0gxWUVQcjVYTVZNVjdnZzNLOVRGVWh6MWJ1VzN4VklTSEh4SHlMV2Myby1fQk9UUkI1LW1rV1VIcjE1Qm9uTmNYcVdXbjVHZkxHelUtOVZIRmxCM1hPa1BoMGR0d19QTEpFY1FsWVd4eVRVOTNQSHBxOHhyZEI2Z25LeUtDd2Nzb2lqZC1OM3J2YzVSMEdMYV9UWUJ3PT0ifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzg3MDEyNjgwLjM0MjcxOCwgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInNpZF9ndWFyZCIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiBudWxsLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiOWNhMGNlYzVjNDBjODA4MzM3YjM1YTliNDZjZjExZjAlN0MxNzU1OTA4NzQ0JTdDMTU1NTE5OTMlN0NUaHUlMkMrMTktRmViLTIwMjYrMDAlM0EyNSUzQTM3K0dNVCJ9LCB7ImRvbWFpbiI6ICIudGlrdG9rLmNvbSIsICJleHBpcmF0aW9uRGF0ZSI6IDE3ODgwMjQxNTcuNjQ4NDE3LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogdHJ1ZSwgIm5hbWUiOiAidHR3aWQiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogIm5vX3Jlc3RyaWN0aW9uIiwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogIjElN0MyODd6N2M5b293ZTQ3U3FzRW1lR1JMT0VYb3ZKb1NiajVBa0pPUDVVWmp3JTdDMTc1NjQ4ODIzMCU3QzRiZGU0ZWQ5ODg4YTM3NjI2NmYxYzA5N2ZkN2JkZWVkNDYxYTkxODNhMWI5MGUzOGUxMDJhNzczM2JmYTdkMTcifSwgeyJkb21haW4iOiAiLnd3dy50aWt0b2suY29tIiwgImV4cGlyYXRpb25EYXRlIjogMTc1NjkxMDY2NywgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IGZhbHNlLCAibmFtZSI6ICJwZXJmX2ZlZWRfY2FjaGUiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogbnVsbCwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogInslMjJleHBpcmVUaW1lc3RhbXAlMjI6MCUyQyUyMml0ZW1JZHMlMjI6WyUyMjc1Mjc5NjQ1NjYwNzcwODI5MDIlMjIlMkMlMjIlMjIlMkMlMjI3NTE5OTI2MjcyMzYxNzc4NDYzJTIyXX0ifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzcxNTM5MjE3LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogZmFsc2UsICJuYW1lIjogImNvb2tpZS1jb25zZW50IiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6ICJub19yZXN0cmljdGlvbiIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJ7JTIyb3B0aW9uYWwlMjI6dHJ1ZSUyQyUyMmdhJTIyOnRydWUlMkMlMjJhZiUyMjp0cnVlJTJDJTIyZmJwJTIyOnRydWUlMkMlMjJsaXAlMjI6dHJ1ZSUyQyUyMmJpbmclMjI6dHJ1ZSUyQyUyMnR0YWRzJTIyOnRydWUlMkMlMjJyZWRkaXQlMjI6dHJ1ZSUyQyUyMmh1YnNwb3QlMjI6dHJ1ZSUyQyUyMnZlcnNpb24lMjI6JTIydjEwJTIyfSJ9LCB7ImRvbWFpbiI6ICIudGlrdG9rLmNvbSIsICJleHBpcmF0aW9uRGF0ZSI6IDE3NzE0NjA2NzMuMzQyODg2LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogdHJ1ZSwgIm5hbWUiOiAidWlkX3R0IiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6IG51bGwsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJjOWI5Y2E5MmRkNjZkZjUxNzNhNTQxZWIwNjk5ZjUzNTc1M2ZmNmMwNmViZDUxYTc0ODJkNDQxOTNhYjMyMmYyIn0sIHsiZG9tYWluIjogIi50aWt0b2suY29tIiwgImV4cGlyYXRpb25EYXRlIjogMTc1OTU1Mzk0NS40OTYwMzcsICJob3N0T25seSI6IGZhbHNlLCAiaHR0cE9ubHkiOiBmYWxzZSwgIm5hbWUiOiAicGFzc3BvcnRfY3NyZl90b2tlbl9kZWZhdWx0IiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6IG51bGwsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJiZDBiMGRkZjZjZjA3ODE1NWQwOTEzODYzMzI3YmE5YSJ9LCB7ImRvbWFpbiI6ICIudGlrdG9rLmNvbSIsICJleHBpcmF0aW9uRGF0ZSI6IDE3NzE0NjA2NzMuMzQzMzI4LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogdHJ1ZSwgIm5hbWUiOiAic3NpZF91Y3BfdjEiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogIm5vX3Jlc3RyaWN0aW9uIiwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogIjEuMC4wLUtEUTRORGsyWlRrek1tVTNPVEkzWVRObVkyVm1NR0kzTkRobE0yTXdNalZqTnpZM01HWTNORFlLR1FpR2lOcWFzTG4zbjE4UWlKV2t4UVlZc3dzNENFQVNTQVFRQXhvR2JXRnNhWFpoSWlBNVkyRXdZMlZqTldNME1HTTRNRGd6TXpkaU16VmhPV0kwTm1ObU1URm1NQSJ9LCB7ImRvbWFpbiI6ICIud3d3LnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzgyNDA4MTU1LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogZmFsc2UsICJuYW1lIjogInRpa3Rva193ZWJhcHBfdGhlbWUiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogbnVsbCwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogImRhcmsifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzg5MTEyNDczLjE0NzcwMywgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IGZhbHNlLCAibmFtZSI6ICJfdHRwIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6ICJub19yZXN0cmljdGlvbiIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICIyeUdZVjVTQUQ3amswOUpPVW1lWlcyTzZxeEoifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzYxMDkyNjczLjc5MDUyLCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogdHJ1ZSwgIm5hbWUiOiAiY21wbF90b2tlbiIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiBudWxsLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiQWdRUUFQUDRGLVJPMG84Qk0yeUxaRjBfOHZBV3ZtZUlfNk5uWU4wVURRIn0sIHsiZG9tYWluIjogIi50aWt0b2suY29tIiwgImV4cGlyYXRpb25EYXRlIjogMTc2MTA5MjY3My43OTAzODIsICJob3N0T25seSI6IGZhbHNlLCAiaHR0cE9ubHkiOiB0cnVlLCAibmFtZSI6ICJtdWx0aV9zaWRzIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6IG51bGwsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICI2ODYzNDQ4MjIxMTQwMDI2Mzc0JTNBOWNhMGNlYzVjNDBjODA4MzM3YjM1YTliNDZjZjExZjAifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzU4NTAwNjczLjc5MDY1MywgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInBhc3Nwb3J0X2F1dGhfc3RhdHVzX3NzIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6ICJub19yZXN0cmljdGlvbiIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJhMDlhNjg0YWNmODYwNmRjYTM1ZDQxYWY4MmZmYzMyZiUyQzRjNTlmNDIzM2Y4NjJkMjk1Yzg0MWE3OWY3NmNkY2E1In0sIHsiZG9tYWluIjogIi50aWt0b2suY29tIiwgImV4cGlyYXRpb25EYXRlIjogMTc1OTU1Mzk0NS40OTU5MDgsICJob3N0T25seSI6IGZhbHNlLCAiaHR0cE9ubHkiOiBmYWxzZSwgIm5hbWUiOiAicGFzc3BvcnRfY3NyZl90b2tlbiIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiAibm9fcmVzdHJpY3Rpb24iLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiYmQwYjBkZGY2Y2YwNzgxNTVkMDkxMzg2MzMyN2JhOWEifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzcxNDYwNjczLjM0MzA5MywgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInNlc3Npb25pZCIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiBudWxsLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiOWNhMGNlYzVjNDBjODA4MzM3YjM1YTliNDZjZjExZjAifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzcxNDYwNjczLjM0MzE3MywgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInNlc3Npb25pZF9zcyIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiAibm9fcmVzdHJpY3Rpb24iLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiOWNhMGNlYzVjNDBjODA4MzM3YjM1YTliNDZjZjExZjAifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzcxNDYwNjczLjM0MzAxOSwgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInNpZF90dCIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiBudWxsLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiOWNhMGNlYzVjNDBjODA4MzM3YjM1YTliNDZjZjExZjAifSwgeyJkb21haW4iOiAiLnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzcxNDYwNjczLjM0MzI2MSwgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInNpZF91Y3BfdjEiLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogbnVsbCwgInNlY3VyZSI6IHRydWUsICJzZXNzaW9uIjogZmFsc2UsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogIjEuMC4wLUtEUTRORGsyWlRrek1tVTNPVEkzWVRObVkyVm1NR0kzTkRobE0yTXdNalZqTnpZM01HWTNORFlLR1FpR2lOcWFzTG4zbjE4UWlKV2t4UVlZc3dzNENFQVNTQVFRQXhvR2JXRnNhWFpoSWlBNVkyRXdZMlZqTldNME1HTTRNRGd6TXpkaU16VmhPV0kwTm1ObU1URm1NQSJ9LCB7ImRvbWFpbiI6ICIud3d3LnRpa3Rvay5jb20iLCAiZXhwaXJhdGlvbkRhdGUiOiAxNzgyNDA4MTU1LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogZmFsc2UsICJuYW1lIjogInRpa3Rva193ZWJhcHBfdGhlbWVfc291cmNlIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6IG51bGwsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJhdXRvIn0sIHsiZG9tYWluIjogIi50aWt0b2suY29tIiwgImV4cGlyYXRpb25EYXRlIjogMTc3MjA0MDE1NC45NTU2MTcsICJob3N0T25seSI6IGZhbHNlLCAiaHR0cE9ubHkiOiB0cnVlLCAibmFtZSI6ICJ0dF9jaGFpbl90b2tlbiIsICJwYXRoIjogIi8iLCAic2FtZVNpdGUiOiBudWxsLCAic2VjdXJlIjogdHJ1ZSwgInNlc3Npb24iOiBmYWxzZSwgInN0b3JlSWQiOiBudWxsLCAidmFsdWUiOiAiMS9BVFF0RG1RemdRaUxaT2U3L1Vjdz09In0sIHsiZG9tYWluIjogIi50aWt0b2suY29tIiwgImhvc3RPbmx5IjogZmFsc2UsICJodHRwT25seSI6IHRydWUsICJuYW1lIjogInR0X2NzcmZfdG9rZW4iLCAicGF0aCI6ICIvIiwgInNhbWVTaXRlIjogImxheCIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IHRydWUsICJzdG9yZUlkIjogbnVsbCwgInZhbHVlIjogIndnQ0VkNWIwLUFSeHZmbDhaXzBuQ2tZZG1MbXVza1hmYnVQTSJ9LCB7ImRvbWFpbiI6ICIudGlrdG9rLmNvbSIsICJleHBpcmF0aW9uRGF0ZSI6IDE3NzE0NjA2NzMuMzQyOTU3LCAiaG9zdE9ubHkiOiBmYWxzZSwgImh0dHBPbmx5IjogdHJ1ZSwgIm5hbWUiOiAidWlkX3R0X3NzIiwgInBhdGgiOiAiLyIsICJzYW1lU2l0ZSI6ICJub19yZXN0cmljdGlvbiIsICJzZWN1cmUiOiB0cnVlLCAic2Vzc2lvbiI6IGZhbHNlLCAic3RvcmVJZCI6IG51bGwsICJ2YWx1ZSI6ICJjOWI5Y2E5MmRkNjZkZjUxNzNhNTQxZWIwNjk5ZjUzNTc1M2ZmNmMwNmViZDUxYTc0ODJkNDQxOTNhYjMyMmYyIn1d')
	
	logged_in = await scraper.executeQueued('login')
	await asyncio.sleep(123)

	if not logged_in:
		print("Login failed or session expired.")
		return

	print(f'i\'m {scraper.username}!')
	
asyncio.run(main())