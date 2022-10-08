from twitter import Twitter, OAuth
t = Twitter(auth=OAuth("", "", "", ""))
# Get your "home" timeline
t.statuses.home_timeline()

# Get a particular friend's timeline
t.statuses.user_timeline(screen_name="boogheta")

# to pass in GET/POST parameters, such as `count`
t.statuses.home_timeline(count=5)

# to pass in the GET/POST parameter `id` you need to use `_id`
t.statuses.show(_id=1234567890)

# Update your status
t.statuses.update(
    status="Using @boogheta's sweet Python Twitter Tools.")
