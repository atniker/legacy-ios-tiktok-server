import datetime

def makeNumber(n):
	if not isinstance(n,(int,float)):raise TypeError("Invalid input")
	if n==0:return"0"
	a=abs(n);s="-"if n<0 else""
	m=[(1e12,"T"),(1e9,"B"),(1e6,"M"),(1e3,"K")]
	for i,(d,x)in enumerate(m):
		if a>=d:
			v=a/d
			if round(v,1)>=1000.0 and i>0:
				nd,nx=m[i-1]
				fv=f"{a/nd:.1f}".replace(".0","")
				return f"{s}{fv}{nx}"
			else:
				fv=f"{v:.1f}".replace(".0","")
				return f"{s}{fv}{x}"

	s = s if len(s) <= 2 else s[:2]
	
	return f"{s}{a}"

def makeDate(timestamp):
	timestamp_dt = datetime.datetime.fromtimestamp(timestamp)
	current_time = datetime.datetime.now()
	delta = current_time - timestamp_dt
	total_seconds = int(delta.total_seconds())

	if total_seconds < 0:
		return timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")

	MINUTE = 60
	HOUR = 3600
	DAY = 86400
	WEEK = 604800
	
	if total_seconds < MINUTE:
		return f"{total_seconds}s"
	elif total_seconds < HOUR:
		return f"{total_seconds // MINUTE}m"
	elif total_seconds < DAY:
		return f"{total_seconds // HOUR}h ago" 
	elif total_seconds < WEEK:
		return f"{total_seconds // DAY}d ago"
	elif total_seconds < (4 * WEEK):
		return f"{total_seconds // WEEK}w"
	else:
		return timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")

def makeVideo(data):
	result = {
		'author': {
			'username': data['author_name'], 
			'avatar': data['author_avatar_url']
		},
		'video': {
			'desc': data['description'],
			'heartCount': data['like_count'],
			'commentCount': data['comment_count'],
			'id': data['id'],
			'video_url': data['video_url']
		}
	}

	return result