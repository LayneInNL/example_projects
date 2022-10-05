import feedparser

d = feedparser.parse('http://feedparser.org/docs/examples/atom10.xml')
result = d['feed']['title']

