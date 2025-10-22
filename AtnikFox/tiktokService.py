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

# async def main():
# 	scraper = TikTokScraper(cookies='')
	
# 	logged_in = await scraper.executeQueued('login')
# 	await asyncio.sleep(123)

# 	if not logged_in:
# 		print("Login failed or session expired.")
# 		return

# 	print(f'i\'m {scraper.username}!')
	

# asyncio.run(main())
