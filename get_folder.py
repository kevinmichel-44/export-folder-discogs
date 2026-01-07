
import discogs_client
import requests
import json
import re
import csv
from pick import pick

#Use prompt for identity and token
identity = input("Enter Discogs identity: ")
token = input("Enter your user token access: ")

d = discogs_client.Client(identity, user_token=token)
try:
    me=d.identity()
    print("Login successful")
except:
    print("Identity or access toekn doesn't exist")

# Create empty list
releases = []
folders = []

# Get all folders from user and create list
collection_folders = me.collection_folders
for collection_folder in collection_folders:
    folders.append(collection_folder.name)

#Choose user folder with prompt menu
title = 'Please choose your Discogs folder: '
option, index = pick(folders, title, indicator='=>', default_index=2)

#Get releases informations from folder
for folder in collection_folders:
    if folder.name == option:
        print('Export releases from', folder.name, 'folder')
        for collection_item in folder.releases:
            release_id = collection_item.id
            release = d.release(release_id)
            artists = []
            labels = []
            catnos = []
            for artist in release.artists:
                artist_filtered_name = re.sub('\(.*\)', '', artist.name)
                artists.append(artist_filtered_name)
            for label in release.labels:
                label_filtered_name = re.sub('\(.*\)', '', label.name)
                labels.append(label_filtered_name)
                catnos.append(label.catno)
            artists = ' - '.join(artists)
            labels = ' - '.join(labels)
            catnos = ' , '.join(catnos)
            genres = ' , '.join(release.genres)
            styles = ' , '.join(release.styles)
            price = ' '.join(str(x) for x in release.marketplace_stats.lowest_price.data.values())
            releases.append({'title': release.title, 'artists': artists, 'labels': labels, 'catno': catnos, 'country': release.country, 'year': release.year, 'genres': genres, 'styles': styles, 'price': price, 'url': release.url })
            print("Export realease successful :", artists, "-", release.title)
            
#Create CSV file
csv_columns = ['title','artists','labels', 'catno', 'country','year','genres','styles','price','url']
csv_file = "export.csv"
try:
    with open(csv_file, 'w') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
        writer.writeheader()
        for data in releases:
            writer.writerow(data)
    print("Export CSV is done")
except IOError:
    print("I/O error")