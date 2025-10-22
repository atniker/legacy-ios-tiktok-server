import uuid, asyncio, time, json, requests, base64, io, re, subprocess, os, traceback
from flask import Flask, request, Response, send_file
from flask_apscheduler import APScheduler

from AtnikFox import tiktokService

app = Flask(__name__)

sessions = {}
session_failure = app.response_class(status=403)

def makeResponse(data):
	return app.response_class(response=json.dumps(data), status=200, mimetype='application/json')

def removeSession(session):
	sessions[session]['api'].close()

	del sessions[session]

def msTokenExists(cookies):
	ms_token = None

	for j in cookies:
		if j['name'] == 'msToken':
			ms_token = j['value']

	if ms_token == None:
		raise Exception('malformed cookies')

	for i in list(sessions):
		if sessions[i]['api'].ms_token == ms_token:
			return i

	return None

def throwOnLogicError(session, endpoint):
	if session not in sessions:
		raise ValueError('dated session')

	sessions[session]['timeouts']['last_hit'] = time.time()

def wipeSessions():
	for i in list(sessions):
		try:
			if time.time() - sessions[i]['timeouts']['last_hit'] > 600:
				try:
					sessions[i]['api'].close()
				except:
					traceback.print_exc()

				del sessions[i]
		except:
			traceback.print_exc()

@app.route('/get_session', methods=['POST'])
async def getSession():
	data = request.get_json()
	result = msTokenExists(json.loads(base64.b64decode(data['cookies'])))
	profile = None;cookies = None

	try:
		if not result:
			result = str(uuid.uuid4())
			scraper = tiktokService.TikTokScraper(data['cookies'])

			sessions[result] = {'timeouts': {'last_hit': time.time()}, 'api': scraper}

			logged_in = await scraper.executeQueued('login_with_cookies')

			if not logged_in:
				raise Exception('unauthorized')

			profile = await sessions[result]['api'].executeQueued('scrape_user_profile', [sessions[result]['api'].username.split('@')[-1]])
			cookies = "; ".join([str(x)+"="+str(y) for x,y in sessions[result]['api'].video_download_cookies.items()])
	except:
		traceback.print_exc()

		try:
			sessions[result]['api'].close()
			pass
		except:
			traceback.print_exc()

		del sessions[result]

		return '', 500

	return makeResponse({
		'result': result, 
		'profile': profile, 
		'download_data': {
			'headers': {
				'Accept-Encoding': 'gzip, deflate, sdch',
				'Accept-Language': 'en-US,en;q=0.8',
				'Upgrade-Insecure-Requests': '1',
				'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36',
				'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
				'Cache-Control': 'max-age=0',
				'referer': 'https://www.tiktok.com/'
			},
			'cookies': cookies
		}
	})

@app.route('/validate_session/<session>')
async def validateSession(session):
	if session not in sessions:
		return session_failure

	scraper = sessions[session]['api']

	return makeResponse({
		'result': session, 
		'profile': await scraper.executeQueued('scrape_user_profile', [scraper.username.split('@')[-1]]), 
		'download_data': {
			'headers': {
				'Accept-Encoding': 'gzip, deflate, sdch',
				'Accept-Language': 'en-US,en;q=0.8',
				'Upgrade-Insecure-Requests': '1',
				'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36',
				'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
				'Cache-Control': 'max-age=0',
				'referer': 'https://www.tiktok.com/'
			},
			'cookies': "; ".join([str(x)+"="+str(y) for x,y in scraper.video_download_cookies.items()])
		}
	})

@app.route('/get_trending/<session>')
async def getTrending(session):
	try:
		throwOnLogicError(session, 'getTrending')
	except:
		return session_failure

	r = await sessions[session]['api'].executeQueued('scrape_tiktok_fyp_videos', [5])
	print(r)

	return makeResponse({"result": r})

@app.route('/get_comments/<username>/<video_id>/<session>')
async def getComments(username, video_id, session):
	try:
		throwOnLogicError(session, 'getComments')
	except:
		return session_failure

	r = await sessions[session]['api'].executeQueued('scrape_video_comments', [username, video_id])

	print(r)

	return makeResponse({'result': r})

@app.route('/get_profile/<username>/<session>')
async def getProfile(username, session):
	try:
		throwOnLogicError(session, 'getProfile')
	except:
		return session_failure

	r = await sessions[session]['api'].executeQueued('scrape_user_profile', [username])

	print(r)

	return makeResponse({'result': r})

@app.route('/get_notifications/<session>')
async def getNotifications(session):
	try:
		throwOnLogicError(session, 'getNotifications')
	except:
		return session_failure

	r = await sessions[session]['api'].executeQueued('scrape_notifications')

	print(r)

	return makeResponse({'result': r})

@app.route('/get_avatar/<session>', methods=['POST'])
def getAvatar(session):
	data = request.get_json()

	print(data['url'])

	if not data['url'].startswith('https://p16'):
		return '', 403

	result = requests.get(data['url'])

	return base64.b64encode(result.content).decode('utf-8')

streamed_cache = {}

@app.route('/get_video/<session>')
def getVideo(session):
	try:
		throwOnLogicError(session, 'getVideo')
	except:
		return session_failure

	print(request.headers)

	data = json.loads(request.headers['url'])

	seed = f'{data["item_id"]}'

	if seed not in streamed_cache:
		r = requests.get(
			data['url'], 
			headers=sessions[session]['api'].gayass['headers'], 
			cookies=sessions[session]['api'].gayass['cookies'],
			timeout=10
		)

		filename = f'assets/cache/{seed}.mp4'

		#open(filename, 'wb').write(r.content)
		streamed_cache[seed] = r.content #processVideo(filename)

	return send_file(io.BytesIO(streamed_cache[seed]), mimetype='video/mp4', as_attachment=False)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()
scheduler.add_job(id='session-wiper', func=wipeSessions, trigger='interval', seconds=10)

app.run(host='0.0.0.0', port=80, threaded=True, debug=False)