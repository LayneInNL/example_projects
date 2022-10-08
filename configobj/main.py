from configobj import ConfigObj
config = ConfigObj()
config.filename = "hello"
#
config['keyword1'] = 1
config['keyword2'] = False
#
section2 = {
    'keyword5': 5,
    'keyword6': 6,
    'sub-section': {
        'keyword7': 7
        }
}
config['section2'] = section2
#
config.write()