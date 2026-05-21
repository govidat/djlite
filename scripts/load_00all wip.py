from scripts.load_00globalval import run as load_00globalval
#from scripts.load_taxonomies import run as load_taxonomies
#from scripts.load_themes import run as load_themes


def run():

    load_00globalval()
    #load_taxonomies()
    #load_themes()

    print("All seed data loaded")