#!/usr/bin/env python

#    Copyright (C) 2009  Chris Targett  <chris@xlevus.net>
#
#    This file is part of TVSlurp.
#
#    TVSlurp is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    TVSlurp is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with TVSlurp.  If not, see <http://www.gnu.org/licenses/>.
#

import re
import logging
import optparse
import warnings
import ConfigParser

from urllib import urlencode
from datetime import datetime
from os.path import expanduser, exists
from urllib2 import urlopen, URLError

from icalendar import Calendar, Event

parser = optparse.OptionParser()
parser.add_option('-d', '--debug', dest='debug', action='store_true', default=False, 
        help='Debugging output')
parser.add_option('-c', '--config', dest='config', default='~/.tvslurp/config', 
        metavar='FILE', help='Location of config file')

DEFAULT_SEARCH_SETTINGS = {
    'category': 8,
    'sortfield': 'date',
    'sortorder': 'asc',
}

class TVSlurp(object):
    search_regex = re.compile(r'(?P<id>\d+?)\s(?P<size>\d+?)\s(?P<name>.*)')
    episode_re = re.compile(r'(?P<show>.*?) - (?P<season>\d+)x(?P<episode>\d+)')
    
    def __init__(self, config_file):
        config = ConfigParser.ConfigParser()
        config.read(config_file)

        try:
            self.newzbin_username = config.get('newzbin', 'username')
            self.newzbin_password = config.get('newzbin', 'password')
        
            self.ical_url = config.get('global', 'ical_url')
        
            self.processed_url_file = open(
                    expanduser(config.get('global', 'processed_url_file')), 'a+')
            self.processed_urls = [ln[:-1] for ln in self.processed_url_file.xreadlines()]    
        
            self.search_params = config._sections['search']
            del self.search_params['__name__']
        except ConfigParser.NoOptionError, e:
            logging.error("Invalid Config: %s" % e)
            exit(1)
    
    def search_newzbin(self, query):
        logging.debug('Searching newzbin for "%s"' % query)
        
        params = self.search_params.copy()
        params['query'] = query
        params['username'] = self.newzbin_username
        params['password'] = self.newzbin_password

        print urlencode(params)
        req = urlopen('http://www.newzbin.com/api/reportfind/', urlencode(params))

        for line in req.readlines():
            match = self.search_regex.match(line)
            if match:
                logging.debug("Found result `%s`" % line.replace('\n',''))
                yield {
                    'id': int(match.group('id')),
                    'size': int(match.group('size')),
                    'name': match.group('name'),
                }
    
    def bookmark_report(self, id):
        logging.debug('Bookmarking report #%s' % id)
        try:
            req = urlopen('http://www.newzbin.com/api/bookmarks/', urlencode({
                    'action': 'add', 
                    'reportids':id,
                    'username': self.newzbin_username, 
                    'password': self.newzbin_password, 
            }))
            req.read()
        except URLError:
            logging.error('Failed to bookmark report.')
    
    def find_episode(self, title):
        try:
            match = self.episode_re.match(title)
            show = match.group('show')
            season = int(match.group('season'))
            episode = int(match.group('episode'))

            return self.search_newzbin("%s %sx%02d" % (show, season, episode))
        except ValueError: # This should never happen. Best to be safe
            return None

    def load_ical(self):
        logging.debug("Loading iCal from url %s" % self.ical_url)
        try:
            req = urlopen(self.ical_url)
            return Calendar.from_string(req.read())
        except URLError:
            logging.error("Unable to retrieve iCal")

    def find_new_shows(self):
        ical = self.load_ical()

        for event in ical.walk():
            if isinstance(event, Event) \
                    and event.decoded('dtend') < datetime.now() \
                    and event['url'] not in self.processed_urls:

                search = list(self.find_episode(event['summary']))
                
                if search:
                    result = search[0]
                    logging.info('Found "%s"' % result['name'])
                    self.bookmark_report(result['id'])
                    self.processed_url_file.write(event['url']+'\n')

if __name__ == '__main__':
    options, args = parser.parse_args()

    if options.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level)

    config_file = expanduser(options.config)
    if not exists(config_file):
        logging.error("Config file '%s' does not exist" % config_file)
        exit(1)

    with warnings.catch_warnings(): # iCalendar uses deprecated functions
        warnings.simplefilter("ignore")
        tvs = TVSlurp(config_file)
        tvs.find_new_shows()
    
