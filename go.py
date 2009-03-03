# (c) 2009 Dave Peck, All Rights Reserved. (http://davepeck.org/)

# This file is part of Dave Peck's Go.

# Dave Peck's Go is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Dave Peck's Go is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with Dave Peck's Go.  If not, see <http://www.gnu.org/licenses/>.


#------
# This file is the appengine back-end to the Go application.
#------

import cgi
import os
import sys
import logging
import copy
import pickle
import random
import string
import traceback
from datetime import datetime, timedelta, date
import simplejson
import wsgiref.handlers

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import mail

import urllib
import urllib2
import base64
import secrets


#------------------------------------------------------------------------------
# Constants
#------------------------------------------------------------------------------

class CONST(object):
    No_Color = 0    
    Black_Color = 1
    White_Color = 2    
    Both_Colors = 3
    Color_Names = ['none', 'black', 'white', 'both']
    Star_Ordinals = [[3, 9, 15], [3, 6, 9], [2, 4, 6]]  
    Board_Sizes = [(19, 19), (13, 13), (9, 9)]
    Board_Classes = ['nineteen_board', 'thirteen_board', 'nine_board']
    Board_Size_Names = ['19 x 19', '13 x 13', '9 x 9']
    Handicaps = [0, 9, 8, 7, 6, 5, 4, 3, 2]
    Handicap_Names = ['plays first', 'has a nine stone handicap', 'has an eight stone handicap', 'has a seven stone handicap', 'has a six stone handicap', 'has a five stone handicap', 'has a four stone handicap', 'has a three stone handicap', 'has a two stone handicap']
    Handicap_Positions = [
        [(15, 3), (3, 15), (15, 15), (3, 3), (9, 9), (3, 9), (15, 9), (9, 3), (9, 15)],
        [(9, 3), (3, 9), (9, 9), (3, 3), (6, 6), (3, 6), (9, 6), (6, 3), (6, 9)],
        [(6, 2), (2, 6), (6, 6), (2, 2), (4, 4)]]
    Email_Contact = "email"
    Twitter_Contact = "twitter"
    No_Contact = "none"
    Default_Email = "nobody@example.com"

def opposite_color(color):
    return 3 - color

def pos_to_coord(pos):
    """Convert a position into letter coordinates, for SGF"""
    x, y = pos
    return "%s%s" % (string.letters[x], string.letters[y])

    
#------------------------------------------------------------------------------
# Exception Handling & AppEngine Helpers
#------------------------------------------------------------------------------

class ExceptionHelper:
    @staticmethod
    def _typename(t):
        """helper function -- isolates the type name from the type string"""
        if t:
            return str(t).split("'")[1]
        else:
            return "{type: None}"

    @staticmethod
    def _typeof(thing):
        """Get the type name, such as str, float, or int"""
        return ExceptionHelper._typename(type(thing))

    @staticmethod
    def exception_string():
        """called to extract useful information from an exception"""
        exc = sys.exc_info()
        exc_type = ExceptionHelper._typename(exc[0])
        exc_message = str(exc[1])
        exc_contents = "".join(traceback.format_exception(*sys.exc_info()))
        return "[%s]\n %s" % (exc_type, exc_contents)

class AppEngineHelper:
    @staticmethod
    def is_production():
        server_software = os.environ["SERVER_SOFTWARE"]
        if not server_software:
            return True
        return "development" not in server_software.lower()

    @staticmethod
    def base_url():
        if AppEngineHelper.is_production():
            return "http://go.davepeck.org/"
        else:
            return "http://localhost:8080/"
        
    
#------------------------------------------------------------------------------
# Game State
#------------------------------------------------------------------------------

class GameBoard(object):
    def __init__(self, board_size_index = 0, handicap_index = 0):
        super(GameBoard, self).__init__()
        self.width = CONST.Board_Sizes[board_size_index][0]
        self.height = CONST.Board_Sizes[board_size_index][1]
        self.size_index = board_size_index
        self.handicap_index = handicap_index
        self._make_board()
        self._apply_handicap()
        
    def _make_board(self):
        self.board = []        
        for x in range(self.width):
            self.board.append( [CONST.No_Color] * self.height )
    
    def _apply_handicap(self):
        stones_handicap = CONST.Handicaps[self.handicap_index]
        positions_handicap = CONST.Handicap_Positions[self.size_index]
        for i in range(stones_handicap):
            self.set(positions_handicap[i][0], positions_handicap[i][1], CONST.Black_Color)                    
    
    def get(self, x, y):
        return self.board[x][y]
    
    def set(self, x, y, color):
        self.board[x][y] = color
    
    def get_width(self):
        return self.width
    
    def get_height(self):
        return self.height

    def get_size_index(self):
        return self.size_index

    def get_komi(self):
        if self.handicap_index:
            return 0.5
        else:
            return 6.5

    def get_handicap(self):
        return CONST.Handicaps[self.handicap_index]

    def get_state_string(self):
        # Used for passing the board state via javascript. Smallish.
        bs = ""
        for y in range(self.height):
            for x in range(self.width):
                piece = self.get(x, y)
                if piece == CONST.Black_Color:
                    bs += "b"
                elif piece == CONST.White_Color:
                    bs += "w"
                else:
                    bs += "."
        return bs

    def is_in_bounds(self, x, y):
        return (x >= 0) and (x < self.get_width()) and (y >= 0) and (y < self.get_height())
        
    def is_stone_in_self_atari(self, x, y):
        liberties = LibertyFinder(self, x, y)
        return liberties.get_liberty_count() == 0

    def _compute_liberties_at(self, x, y, other):
        # returns number of liberties and connected stones
        if not self.is_in_bounds(x, y):
            return (0, [])

        if self.get(x, y) != other:
            return (0, [])

        finder = LibertyFinder(self, x, y)
        return (finder.get_liberty_count(), finder.get_connected_stones())
                
    def compute_atari_and_captures(self, x, y):        
        color = self.get(x, y)
        other = opposite_color(color)

        liberties = []
        liberties.append(self._compute_liberties_at(x-1, y, other))
        liberties.append(self._compute_liberties_at(x, y-1, other))
        liberties.append(self._compute_liberties_at(x+1, y, other))
        liberties.append(self._compute_liberties_at(x, y+1, other))

        ataris = 0
        captures = []

        # determine ataris and first pass on captured
        # (there may be duplicate captured stones at first)
        for count, connected in liberties:
            if count == 1:
                ataris += 1
            if count == 0:
                captures.append(connected)

        # remove duplicate captures
        nodup_captures = []
        for capture in captures:
            if capture not in nodup_captures:
                nodup_captures.append(capture)

        # flatten all captured stones into one batch
        final_captures = []
        for capture in nodup_captures:
            for x, y in capture:
                final_captures.append((x, y))

        return (ataris, final_captures)

    def get_class(self):
        return CONST.Board_Classes[self.size_index]
    
    def clone(self):
        return copy.deepcopy(self)    

class GameState(object):
    def __init__(self):
        super(GameState, self).__init__()
        self.board = None
        self.white_stones_captured = 0
        self.black_stones_captured = 0
        self.whose_move = CONST.No_Color
        self.last_move_message = "It's your turn to move; this is the first move of the game."
        self.current_move_number = 0
        self.last_move = (-1, -1)
        self.last_move_was_pass = False
    
    def get_board(self):
        return self.board
        
    def set_board(self, board):
        self.board = board        
        
    def get_whose_move(self):
        return self.whose_move

    def set_whose_move(self, whose_move):
        self.whose_move = whose_move
        
    def get_white_stones_captured(self):
        return self.white_stones_captured
    
    def set_white_stones_captured(self, wsc):
        self.white_stones_captured = wsc
    
    def get_black_stones_captured(self):
        return self.black_stones_captured
        
    def set_black_stones_captured(self, bsc):
        self.black_stones_captured = bsc

    def get_last_move_message(self):
        return self.last_move_message

    def set_last_move_message(self, message):
        self.last_move_message = message

    def get_current_move_number(self):
        return self.current_move_number

    def set_current_move_number(self, number):
        self.current_move_number = number

    def increment_current_move_number(self, by = 1):
        self.current_move_number += by

    def get_last_move(self):
        return self.last_move

    def set_last_move(self, x, y):
        self.last_move = (x, y)

    def get_last_move_was_pass(self):
        return self.last_move_was_pass

    def set_last_move_was_pass(self, was_pass):
        self.last_move_was_pass = was_pass
        
    def clone(self):
        clone = GameState()
        clone.white_stones_captured = self.white_stones_captured
        clone.black_stones_captured = self.black_stones_captured
        clone.whose_move = self.whose_move
        clone.last_move_message = self.last_move_message
        clone.current_move_number = self.current_move_number
        clone.board = self.board.clone()
        clone.last_move = self.last_move
        clone.last_move_was_pass = self.last_move_was_pass
        return clone

class ChatEntry(object):
    def __init__(self, cookie, message, current_move_number):
        super(ChatEntry, self).__init__()
        self.cookie = cookie
        self.message = message
        self.move_number = current_move_number

    def get_cookie(self):
        return self.cookie

    def get_message(self):
        return self.message

    def get_move_number(self):
        return self.move_number

    def get_player(self):
        return ModelCache.player_by_cookie(self.cookie)
    
    def get_player_friendly_name(self):
        return self.get_player().get_friendly_name()

    def get_player_email(self):
        return self.get_player().email
    

#------------------------------------------------------------------------------
# LibertyFinder: given a stone, find all connected stones and count liberties
#------------------------------------------------------------------------------

class LibertyFinder(object):
    def __init__(self, board, start_x, start_y):
        super(LibertyFinder, self).__init__()
        self.board = board
        self.start_x = start_x
        self.start_y = start_y        
        self.color = self.board.get(self.start_x, self.start_y)        
        self.connected_stones = []
        self.liberty_count = -1
        self._make_found()
        self._find_connected_stones()
        self._count_liberties()

    def _make_found(self):
        w = self.board.get_width()
        h = self.board.get_height()
        
        self.reached = []        
        for x in range(w):
            self.reached.append([False] * h)
        
    def _find_connected_stones(self):
        q = [(self.start_x, self.start_y)]

        # Flood-fill on the color
        while len(q) > 0:
            # dequeue
            x, y = q[0]
            q = q[1:]

            self.reached[x][y] = True
            self.connected_stones.append((x, y))

            # left
            if (x-1) >= 0:
                left = self.board.get(x-1, y)
                if left == self.color and not self.reached[x-1][y]:
                    q.append((x-1, y))

            # top
            if (y-1) >= 0:
                top = self.board.get(x, y-1)
                if top == self.color and not self.reached[x][y-1]:
                    q.append((x, y-1))

            # right
            if (x+1) < self.board.get_width():
                 right = self.board.get(x+1, y)
                 if right == self.color and not self.reached[x+1][y]:
                     q.append((x+1, y))

            # bottom
            if (y+1) < self.board.get_height():
                bottom = self.board.get(x, y+1)
                if bottom == self.color and not self.reached[x][y+1]:
                    q.append((x, y+1))

        # force a canoncial order for connected stones
        # so that we can determine if two sets of
        # connected stones are the same
        self.connected_stones.sort()

    def _get_liberty_count_at(self, x, y, w, h, already_counted):
        libs = 0
        
        # left liberty?
        if (x-1) >= 0:        
            left = self.board.get(x-1, y)
            if left == CONST.No_Color and not already_counted[x-1][y]:
                libs += 1
                already_counted[x-1][y] = True

        # top liberty?
        if (y-1) >= 0:
            top = self.board.get(x, y-1)
            if top == CONST.No_Color and not already_counted[x][y-1]:
                libs += 1
                already_counted[x][y-1] = True

        # right liberty?
        if (x+1) < w:
            right = self.board.get(x+1, y)
            if right == CONST.No_Color and not already_counted[x+1][y]:
                libs += 1
                already_counted[x+1][y] = True

        # bottom liberty?
        if (y+1) < h:
            bottom = self.board.get(x, y+1)
            if bottom == CONST.No_Color and not already_counted[x][y+1]:
                libs += 1
                already_counted[x][y+1] = True
                
        return libs
        
    def _count_liberties(self):
        w = self.board.get_width()
        h = self.board.get_height()
        already_counted = []        
        for x in range(w):
            already_counted.append([False] * h)
            
        self.liberty_count = 0
        for connected_stone in self.connected_stones:
            x, y = connected_stone
            self.liberty_count += self._get_liberty_count_at(x, y, w, h, already_counted)
            
    def get_liberty_count(self):
        return self.liberty_count
    
    def get_connected_stones(self):
        return self.connected_stones
        
    
#------------------------------------------------------------------------------
# Game Cookies: How to get back to the game
#------------------------------------------------------------------------------

class GameCookie(object):    
    @staticmethod
    def _base_n(num, base):
        # Works for 2 <= n <= 62
        return ((num == 0) and "0") or (GameCookie._base_n(num // base, base).lstrip("0") + "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"[num % base])

    @staticmethod
    def _base_62(num):
        # A nice base to use -- over fifty billion values in just six characters. The power!
        return GameCookie._base_n(num, 62)

    @staticmethod
    def random_cookie():
        # Random, but not necessarily unique
        return GameCookie._base_62(random.randint(1, 50000000000))
    
    @staticmethod
    def unique_pair():
        # Return two guaranteed-unique (and non-identical) cookies
        unique = False
        
        while not unique:
            one = GameCookie.random_cookie()
            two = GameCookie.random_cookie()
            while one == two:
                two = GameCookie.random_cookie()
            test_one = Player.all().filter('cookie =', one).get()
            test_two = Player.all().filter('cookie =', two).get()
            unique = (test_one is None) and (test_two is None)
        
        return (one, two)
                            

#------------------------------------------------------------------------------
# Code to help with sending out emails.
#------------------------------------------------------------------------------

class EmailHelper(object):
    No_Reply_Address = "Dave Peck's Go <no-reply@davepeck.org>"
    
    @staticmethod
    def _rfc_address(name, email):
        return "%s <%s>" % (name, email)

    @staticmethod
    def _game_url(cookie):
        return "%splay/%s/" % (AppEngineHelper.base_url(), cookie)

    @staticmethod
    def notify_you_new_game(your_name, your_email, your_cookie, opponent_name, your_turn):
        your_address = EmailHelper._rfc_address(your_name, your_email)
        your_message = mail.EmailMessage()
        your_message.sender = EmailHelper.No_Reply_Address
        your_message.subject = "[GO] You've started a game with %s" % opponent_name
        your_message.to = your_address
        your_message.body = """
Hi %s,

You've started a game of Go with %s. You can see what's happening by visiting:

%s

""" % (your_name, opponent_name, EmailHelper._game_url(your_cookie))

        if your_turn:
            your_message.body += "Also, it's your turn to move first!"
        else:
            your_message.body += "Your opponent plays first; you'll get an email when it's your turn to move."

        # SEND your message!
        your_message.send()

    @staticmethod
    def notify_opponent_new_game(your_name, opponent_name, opponent_email, opponent_cookie, your_turn):
        opponent_address = EmailHelper._rfc_address(opponent_name, opponent_email)
        opponent_message = mail.EmailMessage()
        opponent_message.sender = EmailHelper.No_Reply_Address
        opponent_message.subject = "[GO] %s has invited you to play!" % your_name
        opponent_message.to = opponent_address
        opponent_message.body = """
Hi %s,

%s started a game of Go with you. You can see what's happening by visiting:

%s

""" % (opponent_name, your_name, EmailHelper._game_url(opponent_cookie))

        if your_turn:
            opponent_message.body += "You'll get another email when it's your turn."
        else:
            opponent_message.body += "It's your turn to move, so get going!"

        # SEND opponent message!
        opponent_message.send()        

        
    @staticmethod
    def notify_your_turn(your_name, your_email, your_cookie, opponent_name, opponent_email):
        your_address = EmailHelper._rfc_address(your_name, your_email)
        opponent_address = EmailHelper._rfc_address(opponent_name, opponent_email)

        message = mail.EmailMessage()
        message.sender = EmailHelper.No_Reply_Address
        message.subject = "[GO] It's your turn against %s" % opponent_name
        message.to = your_address
        message.body = """
It's your turn to make a move against %s. Just follow this link:

%s

""" % (opponent_name, EmailHelper._game_url(your_cookie))

        message.send()


#------------------------------------------------------------------------------
# Twitter Support
#------------------------------------------------------------------------------

class TwitterHelper(object):
    @staticmethod
    def _open_basic_auth_url(username, password, url, params):
        # The "right" way to do this with urllib2 sucks. Why bother?
        data = None
        if params is not None:
            data = urllib.urlencode(params)
        req = urllib2.Request(url, data)
        base64string = base64.encodestring('%s:%s' % (username, password))[:-1]
        authheader =  "Basic %s" % base64string
        req.add_header("Authorization", authheader)
        try:
            handle = urllib2.urlopen(req)
        except:
            logging.warn("Failed to make twitter request: %s" % ExceptionHelper.exception_string())
            return None
        return handle

    @staticmethod
    def _make_twitter_call_as(url, params, user, user_password):
        handle = TwitterHelper._open_basic_auth_url(user, user_password, url, params)
        if handle is None:
            return None        
        try:
            result = simplejson.loads(handle.read())
        except:
            logging.warn("Couldn't process json result from twitter: %s" % ExceptionHelper.exception_string())
            return None
        return result        
    
    @staticmethod
    def _make_twitter_call(url, params):
        return TwitterHelper._make_twitter_call_as(url, params, secrets.twitter_user, secrets.twitter_pass)
        
    @staticmethod
    def _make_boolean_twitter_call(url, params):
        result = TwitterHelper._make_twitter_call(url, params)
        if result is None:
            return None
        if type(result) != type(True):
            return None
        return result

    @staticmethod
    def _make_success_twitter_call(url, params):
        result = TwitterHelper._make_twitter_call(url, params)
        if result is None:
            return None
        return not ('error' in result)

    @staticmethod
    def _make_success_twitter_call_as(url, params, user, user_password):
        result = TwitterHelper._make_twitter_call_as(url, params, user, user_password)
        if result is None:
            return None
        return not ('error' in result)
    
    @staticmethod
    def _game_url(cookie):
        return "%splay/%s/" % (AppEngineHelper.base_url(), cookie)
    
    @staticmethod
    def _trim_name(name):
        return name.strip()[:16]
    
    @staticmethod
    def does_follow(a, b):
        # Does "a" follow "b"?
        return TwitterHelper._make_boolean_twitter_call("http://twitter.com/friendships/exists.json", {"user_a": a, "user_b": b})

    @staticmethod
    def are_mutual_followers(a, b):
        a_b = TwitterHelper.does_follow(a, b)
        if a_b is None:
            return None
        if not a_b:
            return False
        b_a = TwitterHelper.does_follow(b, a)
        if b_a is None:
            return None
        return b_a

    @staticmethod
    def create_follow(a, b, a_password):
        # {"ignore": "this"} forces a POST
        return TwitterHelper._make_success_twitter_call_as("http://twitter.com/friendships/create/%s.json?follow=true" % b, {"ignore": "this"}, a, a_password)

    @staticmethod
    def does_go_account_follow_user(user):
        return TwitterHelper.does_follow(secrets.twitter_user, user)

    @staticmethod
    def does_user_follow_go_account(user):
        return TwitterHelper.does_follow(user, secrets.twitter_user)
    
    @staticmethod
    def make_go_account_follow_user(user):
        did = TwitterHelper.create_follow(secrets.twitter_user, user, secrets.twitter_pass)
        if did is None:
            return False
        return did

    @staticmethod
    def make_user_follow_go_account(user, user_password):
        did = TwitterHelper.create_follow(user, secrets.twitter_user, user_password)
        if did is None:
            return False
        return did

    @staticmethod
    def send_direct_message(a, b, a_password, message):
        success = TwitterHelper._open_basic_auth_url(a, a_password, "http://twitter.com/direct_messages/new.json", {"user": b, "text": message})
        return (success is not None)

    @staticmethod
    def send_notification_to_user(user, message):
        return TwitterHelper.send_direct_message(secrets.twitter_user, user, secrets.twitter_pass, message)
    
    @staticmethod
    def notify_you_new_game(your_name, your_twitter, your_cookie, opponent_name, your_turn):
        if your_turn:
            message = "You've started a game of Go with %s. It is your turn. You can play by visiting %s" % (TwitterHelper._trim_name(opponent_name), TwitterHelper._game_url(your_cookie))
        else:            
            message = "You've started a game of Go with %s. You can see what's happening by visiting %s" % (TwitterHelper._trim_name(opponent_name), TwitterHelper._game_url(your_cookie))
        return TwitterHelper.send_notification_to_user(your_twitter, message)

    @staticmethod
    def notify_opponent_new_game(your_name, opponent_name, opponent_twitter, opponent_cookie, your_turn):
        if your_turn:
            message = "%s has started a game of Go with you. You can see what's happening by visiting %s" % (TwitterHelper._trim_name(your_name), TwitterHelper._game_url(opponent_cookie))
        else:            
            message = "%s has started a game of Go with you. It's your turn. You can play by visiting %s" % (TwitterHelper._trim_name(your_name), TwitterHelper._game_url(opponent_cookie))
        return TwitterHelper.send_notification_to_user(opponent_twitter, message)
    
    @staticmethod
    def notify_your_turn(your_name, your_twitter, your_cookie, opponent_name, move_message):
        if move_message == "It's your turn to move.":
            # TODO UNHACK -- ugly, but I'm too lazy to do this well at the moment.
            message = "%s moved; it's now your turn." % TwitterHelper._trim_name(opponent_name)
        else:
            message = move_message
        message += " " + TwitterHelper._game_url(your_cookie)
        return TwitterHelper.send_notification_to_user(your_twitter, message)    
        
        
#------------------------------------------------------------------------------
# Models
#------------------------------------------------------------------------------

class ModelCache(object):
    @staticmethod
    def player_by_cookie(cookie):
        player = memcache.get(cookie)
        if player is not None:
            return player
        else:
            player = Player.all().filter("cookie = ", cookie).get()
            if player is not None:
                memcache.set(cookie, player)
            return player
        
    @staticmethod
    def clear_cookie(cookie):
        memcache.delete(cookie)
        
class Game(db.Model):
    date_created = db.DateTimeProperty(auto_now = True)
    date_last_moved = db.DateTimeProperty(auto_now = True)    
    history = db.ListProperty(db.Blob)
    current_state = db.BlobProperty()

    # Back reference the players
    black_cookie = db.StringProperty()
    white_cookie = db.StringProperty()

    # Recent chat
    chat_history = db.ListProperty(db.Blob)

    is_finished = db.BooleanProperty(default=False)

    def get_black_player(self):
        return ModelCache.player_by_cookie(self.black_cookie)

    def get_white_player(self):
        return ModelCache.player_by_cookie(self.white_cookie)
    
    def get_black_friendly_name(self):
        return self.get_black_player().get_friendly_name()

    def get_white_friendly_name(self):
        return self.get_white_player().get_friendly_name()

    def get_current_move_number(self):
        # 1.0 shipped with a bug that caused the zeroth state to
        # have current_move_number set to 1. That sorta sucks for history
        # and this little code fixes it. I probably would have ignored the issue
        # but there are over 100 games running on the production site at the moment.
        if self.history is None:
            return 0
        return len(self.history)
    
    # 1.0 shipped without chat, so some games may not have this.
    # hence this helper routine.
    def get_chat_history_blobs(self):
        # We shipped without chat, so some games may not have this
        blob_history = None
        try:
            blob_history = self.chat_history
        except:
            blob_history = None

        if blob_history is None:
            self.chat_history = []
            self.put()
            blob_history = []

        return blob_history
                

# Because there is no notion of 'account', players are created
# anew each time a game is constructed.

# NOTE:
# All of the contact and "email vs. twitter" stuff is a little
# rough around the edges. That's because go.davepeck.org launched without
# twitter, and I've got to make sure old player objects continue to behave
# well. I decided to use a less-than-ideal representation so that I didn't
# have to go back and fix all the old player objects.
    
class Player(db.Model):
    game = db.ReferenceProperty(Game)
    cookie = db.StringProperty()
    color = db.IntegerProperty(default=CONST.No_Color)
    name = db.StringProperty()
    email = db.EmailProperty()
    wants_email = db.BooleanProperty(default=True)
    twitter = db.StringProperty()
    wants_twitter = db.BooleanProperty(default=False)
    contact_type = db.StringProperty(default=CONST.Email_Contact)

    def get_safe_email(self):
        try:
            safe_email = self.email
        except:
            safe_email = None
        if safe_email is None:
            return ""
        if safe_email == CONST.Default_Email:
            return ""
        return safe_email

    def get_safe_twitter(self):
        try:
            safe_twitter = self.twitter
        except:
            safe_twitter = None
        if safe_twitter is None:
            return ""
        return safe_twitter
    
    def get_opponent(self):
        opponent_color = opposite_color(self.color)
        if opponent_color == CONST.Black_Color:
            return self.game.get_black_player()
        else:
            return self.game.get_white_player()

    def get_friendly_name(self):
        friendly_name = self.name
        at_loc = friendly_name.find('@')
        if at_loc != -1:
            friendly_name = friendly_name[:at_loc]
        if len(friendly_name) > 18:
            friendly_name = friendly_name[:15] + '...'
        return friendly_name

    def does_want_twitter(self):
        # Smooth over the fact that this property wasn't here in the past.
        try:
            wants = self.wants_twitter
        except:
            wants = False
        if wants is None:
            return False
        return wants

    def get_active_contact_type(self):
        if self.wants_email:
            return CONST.Email_Contact
        elif self.does_want_twitter():
            return CONST.Twitter_Contact
        else:
            return CONST.No_Contact

    def get_contact_type(self):
        try:
            c_t = self.contact_type
        except:
            c_t = CONST.Email_Contact
        if c_t is None:
            return CONST.Email_Contact
        return c_t

    def get_contact(self):
        if self.wants_email:
            return self.email
        elif self.does_want_twitter():
            return self.twitter
        c_t = self.get_contact_type()
        if c_t == CONST.Email_Contact:
            return self.email
        else:
            return self.twitter

        
#------------------------------------------------------------------------------
# Base Handler
#------------------------------------------------------------------------------

class GoHandler(webapp.RequestHandler):
    def __init__(self):
        super(GoHandler, self).__init__()
    
    def _template_path(self, filename):
        return os.path.join(os.path.dirname(__file__), 'templates', filename)
        
    def render_json(self, obj):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(simplejson.dumps(obj))
    
    def render_text(self, text):
        self.response.headers['Content-Type'] = 'text/plain'        
        self.response.out.write(text)
                
    def render_template(self, filename, template_args=None, content_type='text/html', **template_extras):
        if not template_args:
            final_args = {}
        else:
            final_args = template_args.copy()
        final_args.update(template_extras)
        self.response.headers['Content-Type'] = content_type
        self.response.out.write(template.render(self._template_path(filename), final_args))
    
    def is_valid_name(self, name):
        return (name is not None) and (len(name) > 0) and (len(name) < 200)
        
    def is_valid_email(self, email):
        # There is no "correct" way to validate an email. 
        # This is the best you can really do.
        if email is None:
            return False
            
        if len(email) <= 4:
            return False
        
        if len(email) > 200:
            return False
            
        i_at = email.find('@')
        i_p = email.find('.')
        i_right_p = email.rfind('.')
        i_last = len(email) - 1
        
        if i_at == -1 or i_p == -1:
            return False

        # @ can't come at front
        if i_at == 0:
            return False
            
        # @ must come before .
        # and there must be a character in between
        if i_at >= (i_right_p - 1):
            return False
        
        # final domain names must be one or more characters
        if i_right_p >= len(email) - 1:
            return False
        
        return True

    def is_valid_twitter(self, twitter):
        if twitter is None:
            return False

        if (len(twitter) < 1) or (len(twitter) > 16):
            return False

        # a python hax0r told me this would be faster than REs for very short strings
        # (TODO validate that claim)
        twitter = twitter.lower()
        for t in twitter:
            if not t in 'abcdefghijklmnopqrstuvwxyz0123456789_':
                return False

        return True

    def is_valid_contact_type(self, contact_type):
        return (contact_type == CONST.Email_Contact) or (contact_type == CONST.Twitter_Contact)

    def is_valid_active_contact_type(self, contact_type):
        return (contact_type == CONST.Email_Contact) or (contact_type == CONST.Twitter_Contact) or (contact_type == CONST.No_Contact)
        
    def is_valid_contact(self, contact, contact_type):
        if contact_type == CONST.Email_Contact:
            return self.is_valid_email(contact)
        else:
            return self.is_valid_twitter(contact)
        

#------------------------------------------------------------------------------
# "Get Going" Handler
#------------------------------------------------------------------------------

class GetGoingHandler(GoHandler):
    def __init__(self):
        super(GetGoingHandler, self).__init__()
    
    def get(self, *args):
        self.render_template("get-going.html")

        
#------------------------------------------------------------------------------
# "Create Game" Handler
#------------------------------------------------------------------------------
        
class CreateGameHandler(GoHandler):
    def __init__(self):
        super(CreateGameHandler, self).__init__()
    
    def fail(self, flash="Invalid input."):
        self.render_json({'success': False, 'need_your_twitter_password': False, 'flash': flash})

    def require_twitter_password(self, flash):
        self.render_json({'success': True, 'need_your_twitter_password': True, 'flash': flash})    

    def create_game(self, your_name, your_contact, your_contact_type, opponent_name, opponent_contact, opponent_contact_type, your_color, board_size_index, handicap_index):
        # Create cookies for accessing the game        
        your_cookie, opponent_cookie = GameCookie.unique_pair()                

        # Create the game state and board blobs
        board = GameBoard(board_size_index, handicap_index)
        state = GameState()
        state.set_board(board)
        state.whose_move = CONST.Black_Color if CONST.Handicaps[handicap_index] == 0 else CONST.White_Color
        
        # Create a game model instance
        game = Game()
        game.history = [] # unused value to make appengine happy
        game.chat_history = []
        game.current_state = db.Blob(pickle.dumps(state))
        if your_color == CONST.Black_Color:
            game.black_cookie = your_cookie
            game.white_cookie = opponent_cookie
        else:
            game.black_cookie = opponent_cookie
            game.white_cookie = your_cookie

        # Whose turn?
        your_turn = (your_color == state.whose_move)
        
        # Write the game to the datastore
        game_key = game.put()

        # Create your player
        your_player = Player()
        your_player.game = game_key
        your_player.cookie = your_cookie
        your_player.color = your_color
        your_player.name = your_name
        your_player.contact_type = your_contact_type
        if your_contact_type == CONST.Email_Contact:
            your_player.email = your_contact
            your_player.wants_email = True
            your_player.twitter = ""
            your_player.wants_twitter = False
            your_email = your_contact
        else:
            your_player.email = CONST.Default_Email
            your_player.wants_email = False
            your_player.twitter = your_contact
            your_player.wants_twitter = True
            your_twitter = your_contact
                
        # Create opponent player
        opponent_player = Player()
        opponent_player.game = game_key
        opponent_player.cookie = opponent_cookie
        opponent_player.color = opposite_color(your_color)
        opponent_player.name = opponent_name
        opponent_player.contact_type = opponent_contact_type
        if opponent_contact_type == CONST.Email_Contact:
            opponent_player.email = opponent_contact
            opponent_player.wants_email = True
            opponent_player.twitter = ""
            opponent_player.wants_twitter = False
            opponent_email = opponent_contact
        else:
            opponent_player.email = CONST.Default_Email
            opponent_player.wants_email = False
            opponent_player.twitter = opponent_contact
            opponent_player.wants_twitter = True
            opponent_twitter = opponent_contact

        # Put the players
        your_player.put()
        opponent_player.put()

        # Send out notification to both players, using desired notification scheme.
        if your_player.wants_email:
            EmailHelper.notify_you_new_game(your_name, your_email, your_cookie, opponent_name, your_turn)
        elif your_player.does_want_twitter():
            TwitterHelper.notify_you_new_game(your_name, your_twitter, your_cookie, opponent_name, your_turn)

        if opponent_player.wants_email:
            EmailHelper.notify_opponent_new_game(your_name, opponent_name, opponent_email, opponent_cookie, your_turn)
        elif opponent_player.does_want_twitter():
            TwitterHelper.notify_opponent_new_game(your_name, opponent_name, opponent_twitter, opponent_cookie, your_turn)        
        
        # Great; the game is created!
        return (your_cookie, your_turn)

    def success(self, your_cookie, your_turn):        
        self.render_json({'success': True, 'need_your_twitter_password': False, 'your_cookie': your_cookie, 'your_turn': your_turn})
    
    def post(self, *args):
        try:
            your_name = self.request.POST.get("your_name")
            your_contact = self.request.POST.get("your_contact")
            opponent_name = self.request.POST.get("opponent_name")
            opponent_contact = self.request.POST.get("opponent_contact")
            your_color = int(self.request.POST.get("your_color"))
            board_size_index = int(self.request.POST.get("board_size_index"))
            handicap_index = int(self.request.POST.get("handicap_index"))
            your_contact_type = self.request.POST.get("your_contact_type")
            opponent_contact_type = self.request.POST.get("opponent_contact_type")
        except:
            self.fail()
            return

        try:            
            your_twitter_password = self.request.POST.get("your_twitter_password")
        except:
            your_twitter_password = None
            
        if (your_color < CONST.Black_Color) or (your_color > CONST.White_Color):
            self.fail("Invalid color.")
            return
        
        if (board_size_index < 0) or (board_size_index >= len(CONST.Board_Sizes)):
            self.fail("Invalid board size.")
            return
        
        if (handicap_index < 0) or (handicap_index >= len(CONST.Handicaps)):
            self.fail("Invalid handicap.")
            return
            
        if not self.is_valid_name(your_name):
            self.fail("Your name is invalid.")
            return

        if not self.is_valid_contact_type(your_contact_type):
            self.fail("Your contact type is invalid.")
            return

        if not self.is_valid_contact_type(opponent_contact_type):
            self.fail("Your opponent's contact type is invalid.")
            return
        
        if not self.is_valid_contact(your_contact, your_contact_type):
            self.fail("Your contact information is invalid.")
            return
            
        if not self.is_valid_name(opponent_name):
            self.fail("Your opponent's name is invalid.")
            return
        
        if not self.is_valid_contact(opponent_contact, opponent_contact_type):
            self.fail("Your opponent's contact information is invalid.")
            return

        #
        # Twitter test cases: if necessary, connect up all contacts so we can direct-message
        #
        
        if your_contact_type == CONST.Twitter_Contact:
            if not TwitterHelper.make_go_account_follow_user(your_contact):
                self.fail("Sorry, but we couldn't contact twitter or couldn't follow your account. Try again soon, or use email for now.")
                return

        if opponent_contact_type == CONST.Twitter_Contact:
            if not TwitterHelper.make_go_account_follow_user(opponent_contact):
                self.fail("Sorry, but we couldn't contact twitter or couldn't follow your opponent's account. Try again soon, or use email for now.")
                return

        if your_contact_type == CONST.Twitter_Contact:
            if your_twitter_password is None:
                if not TwitterHelper.does_user_follow_go_account(your_contact):
                    self.require_twitter_password("In order to play go using twitter, you most follow the @%s account. Enter your password to set this up automatically:" % secrets.twitter_user)
                    return
                # success -- you're already following @davepeckgo
            else:
                if not TwitterHelper.make_user_follow_go_account(your_contact, your_twitter_password):
                    self.require_twitter_password("Sorry, either your password is incorrect or we couldn't contact twitter. Try entering your password again, or use email for now.")
                    return
                # success -- you're now following @davepeckgo

        if opponent_contact_type == CONST.Twitter_Contact:
            if not TwitterHelper.does_user_follow_go_account(opponent_contact):
                self.fail("Sorry, but your opponent is not following @%s on twitter. Because of this, you should use email to start the game with your opponent." % secrets.twitter_user)
                return
            # success -- opponent is following @davepeckgo
            
        try:
            your_cookie, your_turn = self.create_game(your_name, your_contact, your_contact_type, opponent_name, opponent_contact, opponent_contact_type, your_color, board_size_index, handicap_index) 
            self.success(your_cookie, your_turn)
        except:
            logging.error("An unexpected error occured in CreateGameHandler: %s" % ExceptionHelper.exception_string())
            self.fail("Sorry, an unexpected error occured. Please try again in a minute or two.")


#------------------------------------------------------------------------------
# "Not Your Turn" Handler
#------------------------------------------------------------------------------

class NotYourTurnHandler(GoHandler):
    def __init__(self):
        super(GetGoingHandler, self).__init__()

    def get(self, *args):
        self.render_template("not-your-turn.html")


#------------------------------------------------------------------------------
# "Play Game" Handler        
#------------------------------------------------------------------------------

class PlayGameHandler(GoHandler):
    def __init__(self):
        super(PlayGameHandler, self).__init__()

    def fail(self, message):
        self.render_template("fail.html", {'message': message})
        
    def get(self, cookie, *args):
        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("No game with that ID could be found.")
            return
        
        game = player.game
        if not game:
            self.fail("Found a reference to a player, but couldn't find the game. Try again in a few minutes?")
            return

        black_player = ModelCache.player_by_cookie(game.black_cookie)
        white_player = ModelCache.player_by_cookie(game.white_cookie)

        if player.color == CONST.Black_Color:
            opponent_player = white_player
        else:
            opponent_player = black_player

        state = pickle.loads(game.current_state)            
        your_move = (state.whose_move == player.color)
        board = state.get_board()

        last_move_x, last_move_y = state.get_last_move()

        items = {
            'your_cookie': cookie,
            'your_color': player.color,
            'you_are_black': player.color == CONST.Black_Color,
            'black_name': black_player.get_friendly_name(),
            'white_name': white_player.get_friendly_name(),
            'board_size_index': board.get_size_index(),
            'board_state_string': board.get_state_string(),
            'black_stones_captured': state.get_black_stones_captured(),
            'white_stones_captured': state.get_white_stones_captured(),
            'your_move': your_move,
            'whose_move': state.whose_move,
            'your_name': player.get_friendly_name(),
            'opponent_name': opponent_player.get_friendly_name(),
            'opponent_contact': opponent_player.get_contact(),
            'opponent_contact_type': opponent_player.get_contact_type(),
            'opponent_contact_is_email': opponent_player.get_contact_type() != CONST.Twitter_Contact,
            'last_move_message': state.get_last_move_message(),
            'wants_email': "true" if player.wants_email else "false",
            'wants_email_python': player.wants_email,
            'current_move_number': game.get_current_move_number(),
            'last_move_x': last_move_x,
            'last_move_y': last_move_y,
            'last_move_was_pass': "true" if state.get_last_move_was_pass() else "false",
            'last_move_was_pass_python': state.get_last_move_was_pass(),
            'has_last_move': last_move_x != -1,
            'game_is_finished': "true" if game.is_finished else "false",
            'game_is_finished_python': game.is_finished,
            'any_captures': (state.get_black_stones_captured() + state.get_white_stones_captured()) > 0,
            'board_class': board.get_class() }
                                
        self.render_template("play.html", items)

        
#------------------------------------------------------------------------------
# "Make This Move" Handler        
#------------------------------------------------------------------------------

class MakeThisMoveHandler(GoHandler):
    def __init__(self):
        super(MakeThisMoveHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           
    
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: found the player but not the game.")
            return

        if game.is_finished:
            self.fail("No more moves can be made; the game is finished.")
            return

        state = pickle.loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        board = state.get_board()
        move_x_str = self.request.POST.get("move_x")
        move_y_str = self.request.POST.get("move_y")
        try:
            move_x = int(move_x_str)
            move_y = int(move_y_str)
        except:
            self.fail("Invalid move x/y coordinate.")
            return

        if (move_x < 0) or (move_x >= board.get_width()) or (move_y < 0) or (move_y >= board.get_height()):
            self.fail("Move coordinates are out-of-bounds.")
            return
        
        piece_at = board.get(move_x, move_y)
        if piece_at != CONST.No_Color:
            self.fail("You can't move here; there is already a stone!")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(opposite_color(player.color))
        new_state.set_last_move_was_pass(False)
        new_board = new_state.get_board()        
        new_board.set(move_x, move_y, player.color)

        # Deal with captures and (new) ataris
        move_message = "It's your turn to move"
        ataris, captures = new_board.compute_atari_and_captures(move_x, move_y)
        if ataris > 0:
            if ataris == 1:
                move_message += "; you were just placed in atari"
            else:
                move_message += "; you were just placed in double atari"

        if len(captures) > 0:
            if ataris == 0:
                move_message += ";"
            else:
                move_message += " and"
            if len(captures) == 1:
                move_message += " one of your stones was captured"
            else:
                move_message += " %d of your stones were captured" % len(captures)

            # actually capture the stones
            for x, y in captures:
                new_board.set(x, y, CONST.No_Color)

            # and count the captures
            if player.color == CONST.Black_Color:
                new_state.set_white_stones_captured(new_state.get_white_stones_captured() + len(captures))
            else:
                new_state.set_black_stones_captured(new_state.get_black_stones_captured() + len(captures))

        # okay, now that we've handled captures, do we have self-atari?
        if new_board.is_stone_in_self_atari(move_x, move_y):
            self.fail("You can't move there; your stone would immediately be captured!")
            return
        
        move_message += "."
        
        new_state.set_last_move_message(move_message)
        new_state.set_last_move(move_x, move_y)
        new_state_string = new_board.get_state_string()

        # Enforce the rule of Ko. If the new state is the same as the last history
        # state (aka two moves back, since we haven't yet appended) then you've
        # violated Ko.
        if len(game.history) > 0:
            two_back_state = pickle.loads(game.history[-1])
            two_back_board = two_back_state.get_board()
            two_back_state_string = two_back_board.get_state_string()
            if two_back_state_string == new_state_string:
                self.fail("Sorry, but this move would violate the <a href=\"http://www.samarkand.net/Academy/learn_go/learn_go_pg8.html\">rule of Ko</a>. Move somewhere else and try playing here later!")
                return
        
        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()        

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email)
        elif opponent.does_want_twitter():
            TwitterHelper.notify_your_turn(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), move_message)
                    
        items = {
            'success': True,
            'flash': 'TODO',
            'current_move_number': game.get_current_move_number(),
            'white_stones_captured': new_state.get_white_stones_captured(),
            'black_stones_captured': new_state.get_black_stones_captured(),
            'board_state_string': new_state_string,
            'last_move_x': move_x,
            'last_move_y': move_y }
                    
        self.render_json(items)


#------------------------------------------------------------------------------
# "Pass" Handler        
#------------------------------------------------------------------------------

class PassHandler(GoHandler):
    def __init__(self):
        super(PassHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           
    
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: found the player but not the game.")
            return

        state = pickle.loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        previous_also_passed = state.get_last_move_was_pass()        

        if previous_also_passed:
            move_message = "The game is over!" 
            game.is_finished = True
        else:
            move_message = "Your opponent passed. You can make a move, or you can pass again to end the game."
        new_state.set_last_move_message(move_message)

        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()        

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email)
        elif opponent.does_want_twitter():
            TwitterHelper.notify_your_turn(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), move_message)
                    
        items = {
            'success': True,
            'flash': 'OK',
            'current_move_number': game.get_current_move_number(),
            'game_is_finished': game.is_finished }
                    
        self.render_json(items)

        
#------------------------------------------------------------------------------
# "Resign" Handler        
#------------------------------------------------------------------------------

class ResignHandler(GoHandler):
    def __init__(self):
        super(ResignHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           
    
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: found the player but not the game.")
            return

        state = pickle.loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        move_message = "The game is over!" 
        game.is_finished = True        
        new_state.set_last_move_message(move_message)

        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()        

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email)
        elif opponent.does_want_twitter():
            TwitterHelper.notify_your_turn(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), move_message)

            
        items = {
            'success': True,
            'flash': 'OK',
            'current_move_number': game.get_current_move_number(),
            'game_is_finished': game.is_finished }
                    
        self.render_json(items)
        
        
#------------------------------------------------------------------------------
# "Has Opponent Moved" Handler        
#------------------------------------------------------------------------------

class HasOpponentMovedHandler(GoHandler):
    def __init__(self):
        super(HasOpponentMovedHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           
        
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: no game found.")
            return

        state = pickle.loads(game.current_state)
        if state.whose_move != player.color:
            self.render_json({'success': True, 'flash': 'OK', 'has_opponent_moved': False})
        else:
            board = state.get_board()
            last_move_x, last_move_y = state.get_last_move()
            self.render_json({
                'success': True,
                'flash': 'OK',
                'has_opponent_moved': True,
                'board_state_string': board.get_state_string(),
                'white_stones_captured': state.get_white_stones_captured(),
                'black_stones_captured': state.get_black_stones_captured(),
                'current_move_number': game.get_current_move_number(),
                'last_move_message': state.get_last_move_message(),
                'last_move_x': last_move_x,
                'last_move_y': last_move_y,
                'last_move_was_pass': state.get_last_move_was_pass(),
                'game_is_finished': game.is_finished})


#------------------------------------------------------------------------------
# "Options" Handler
#------------------------------------------------------------------------------

class OptionsHandler(GoHandler):
    def __init__(self):
        super(OptionsHandler, self).__init__()

    def fail(self, message):
        self.render_template("fail.html", {'message': message})
    
    def get(self, cookie, *args):
        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("No game with that ID could be found.")
            return

        items = {
            'your_cookie': cookie,
            'your_email': player.get_safe_email(),
            'your_twitter': player.get_safe_twitter(),
            'your_contact_type': player.get_active_contact_type() }

        self.render_template("options.html", items)
        

#------------------------------------------------------------------------------
# "Change Options" Handler
#------------------------------------------------------------------------------

class ChangeOptionsHandler(GoHandler):
    def __init__(self):
        super(ChangeOptionsHandler, self).__init__()

    def fail(self, flash="Invalid input."):
        self.render_json({'success': False, 'need_your_twitter_password': False, 'flash': flash})

    def require_twitter_password(self, flash):
        self.render_json({'success': True, 'need_your_twitter_password': True, 'flash': flash})    

    def success(self):        
        self.render_json({'success': True, 'need_your_twitter_password': False, 'flash': 'OK'})
        
    def handle_none(self, player):
        try:
            player.wants_email = False
            player.wants_twitter = False
            try:
                player.put()
            except:
                player.put()                
            ModelCache.clear_cookie(player.cookie)
        except:
            self.fail('Sorry, but we had a timeout; please try again later.')
        else:
            self.success()

    def handle_email(self, player, email):
        if not self.is_valid_email(email):
            self.fail('Invalid email address.')
            return
        
        try:
            player.wants_email = True
            player.wants_twitter = False
            player.contact_type = CONST.Email_Contact
            player.email = email
            try:
                player.put()
            except:
                player.put()                
            ModelCache.clear_cookie(player.cookie)
        except:
            self.fail('Sorry, but we had a timeout; please try again later.')
        else:
            self.success()

    def handle_twitter(self, player, twitter):
        if not self.is_valid_twitter(twitter):
            self.fail('Invalid twitter account.')
            return

        if not TwitterHelper.make_go_account_follow_user(twitter):
            self.fail("Sorry, but we couldn't contact twitter or couldn't follow your account. Try again soon, or use email for now.")
            return

        try:
            your_twitter_password = self.request.POST.get("your_twitter_password")
        except:
            your_twitter_password = None

        if your_twitter_password is None:
            if not TwitterHelper.does_user_follow_go_account(twitter):
                self.require_twitter_password("In order to play go using twitter, you most follow the @%s account. Enter your password to set this up automatically:" % secrets.twitter_user)
                return
            # success -- you're already following @davepeckgo
        else:
            if not TwitterHelper.make_user_follow_go_account(twitter, your_twitter_password):
                self.require_twitter_password("Sorry, either your password is incorrect or we couldn't contact twitter. Try entering your password again, or use email for now.")
                return
            # success -- you're now following @davepeckgo
                
        try:
            player.wants_email = False
            player.wants_twitter = True
            player.contact_type = CONST.Twitter_Contact
            player.twitter = twitter
            try:
                player.put()
            except:
                player.put()                
            ModelCache.clear_cookie(player.cookie)
        except:
            self.fail('Sorry, but we had a timeout; please try again later.')
        else:
            self.success()
    
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        try:
            new_contact_type = self.request.POST.get("new_contact_type")
        except:
            new_contact_type = None
            
        if (new_contact_type is None) or (not self.is_valid_active_contact_type(new_contact_type)):
            self.fail("Unexpected error: invalid contact type.")
            return

        new_contact = None
        if new_contact_type != CONST.No_Contact:
            try:
                new_contact = self.request.POST.get("new_contact")
            except:
                new_contact = None

            if new_contact is None:
                self.fail("Unexpected error: invalid contact.")
                return
        
        if new_contact_type == CONST.Email_Contact:
            self.handle_email(player, new_contact)
        elif new_contact_type == CONST.Twitter_Contact:
            self.handle_twitter(player, new_contact)
        else:
            self.handle_none(player)

            
#------------------------------------------------------------------------------
# "Recent Chat" Handler     
#------------------------------------------------------------------------------

class RecentChatHandler(GoHandler):
    def __init__(self):
        super(RecentChatHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           

    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: couldn't find game for player.")
            return

        blob_history = game.get_chat_history_blobs()
        recent_blobs = blob_history[-10:]
        recent_blobs.reverse()
        recent_chats = []
        
        for blob in recent_blobs:
            entry = pickle.loads(blob)
            recent_chats.append({'name': entry.get_player_friendly_name(), 'message': entry.get_message(), 'move_number': entry.get_move_number()})

        self.render_json({'success': True, 'flash': 'OK', 'chat_count': len(blob_history), 'recent_chats': recent_chats})


#------------------------------------------------------------------------------
# "Add Chat" Handler     
#------------------------------------------------------------------------------

class AddChatHandler(GoHandler):
    def __init__(self):
        super(AddChatHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           

    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return
        
        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: couldn't find game for player.")
            return

        state = pickle.loads(game.current_state)
        
        # Message, etc.
        message = self.request.POST.get("message")
        if message is None:
            self.fail("Unexpected error: couldn't find game for player.")
            return

        if len(message) > 140:
            message = message[:136] + '...'

        clean_message = cgi.escape(message)

        # force game to have chat history
        blob_history = game.get_chat_history_blobs()
        entry = ChatEntry(cookie, clean_message, state.get_current_move_number())
        blob_history.append(db.Blob(pickle.dumps(entry)))
        game.chat_history = blob_history

        try:
            game.put()
        except:
            game.put()

        recent_blobs = blob_history[-10:]
        recent_blobs.reverse()
        recent_chats = []
        
        for blob in recent_blobs:
            entry = pickle.loads(blob)
            recent_chats.append({'name': entry.get_player_friendly_name(), 'message': entry.get_message(), 'move_number': entry.get_move_number()})

        self.render_json({'success': True, 'flash': 'OK', 'chat_count': len(blob_history), 'recent_chats': recent_chats})
                        

#------------------------------------------------------------------------------
# "History" Handler (for main history html page)        
#------------------------------------------------------------------------------

class HistoryHandler(GoHandler):
    def __init__(self):
        super(HistoryHandler, self).__init__()

    def fail(self, message):
        self.render_template("fail.html", {'message': message})
        
    def get(self, cookie, *args):
        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("No game with that ID could be found.")
            return
        
        game = player.game
        if not game:
            self.fail("Found a reference to a player, but couldn't find the game. Try again in a few minutes?")
            return

        black_player = ModelCache.player_by_cookie(game.black_cookie)
        white_player = ModelCache.player_by_cookie(game.white_cookie)

        if player.color == CONST.Black_Color:
            opponent_player = white_player
        else:
            opponent_player = black_player

        state = pickle.loads(game.current_state)            
        your_move = (state.whose_move == player.color)
        board = state.get_board()

        last_move_x, last_move_y = state.get_last_move()

        items = {
            'your_cookie': cookie,
            'your_color': player.color,
            'board_size_index': board.get_size_index(),            
            
            'board_state_string': board.get_state_string(),
            'white_stones_captured': state.get_white_stones_captured(),
            'black_stones_captured': state.get_black_stones_captured(),
            'max_move_number': state.current_move_number,
            'last_move_message': state.get_last_move_message(),
            'last_move_x': last_move_x,
            'last_move_y': last_move_y,
            'last_move_was_pass': "true" if state.get_last_move_was_pass() else "false",
            'whose_move': state.whose_move,
            
            'white_name': white_player.get_friendly_name(),
            'black_name': black_player.get_friendly_name(),
            'board_class': board.get_class(),
            'you_are_black': player.color == CONST.Black_Color
        }
                                
        self.render_template("history.html", items)


#------------------------------------------------------------------------------
# "Get Historical State" Handler       
#------------------------------------------------------------------------------

class GetHistoricalStateHandler(GoHandler):
    def __init__(self):
        super(GetHistoricalStateHandler, self).__init__()

    def fail(self, message):
        self.render_json({'success': False, 'flash': message})           
        
    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        player = ModelCache.player_by_cookie(cookie)
        if not player:
            self.fail("Unexpected error: invalid player.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: no game found.")
            return

        move_number = None
        try:
            move_number = int(self.request.POST.get("move_number"))
        except:
            move_number = None
        if move_number is None:
            self.fail("Unexpected error: must specify a move number.")
            return

        requested_state = None
        if move_number >= len(game.history):
            requested_state = game.current_state
        elif (move_number >= 0) and (move_number < len(game.history)):
            requested_state = game.history[move_number]
        else:
            self.fail("Unexpected error: move number is out of range.")
            return

        state = pickle.loads(requested_state)
        
        board = state.get_board()
        last_move_x, last_move_y = state.get_last_move()
                
        self.render_json({
            'success': True,
            'flash': 'OK',
            'board_state_string': board.get_state_string(),
            'white_stones_captured': state.get_white_stones_captured(),
            'black_stones_captured': state.get_black_stones_captured(),
            'current_move_number': move_number,
            'last_move_message': state.get_last_move_message(),
            'last_move_x': last_move_x,
            'last_move_y': last_move_y,
            'last_move_was_pass': state.get_last_move_was_pass(),
            'whose_move': state.whose_move})
        
#------------------------------------------------------------------------------
# "SGF" Handler (for SGF download)        
#------------------------------------------------------------------------------

class SGFHandler(GoHandler):
    def __init__(self):
        super(SGFHandler, self).__init__()

    def fail(self, message):
        self.render_template("fail.html", {'message': message})

    def get(self, cookie, *args):
        player = ModelCache.player_by_cookie(cookie)
        if not player:
            # XXX Should 404.
            self.fail("No game with that ID could be found.")
            return
        
        game = player.game
        if not game:
            # XXX Should 500?
            self.fail("Found a reference to a player, but couldn't find the game. Try again in a few minutes?")
            return

        black_player = ModelCache.player_by_cookie(game.black_cookie)
        white_player = ModelCache.player_by_cookie(game.white_cookie)

        current_state = pickle.loads(game.current_state)
        board = current_state.get_board()

        handicap = board.get_handicap()
        positions_handicap = CONST.Handicap_Positions[board.get_size_index()]
        handicap_stones = [pos_to_coord(positions_handicap[i]) for i in range(handicap)]

        moves = []
        mover = " BW"
        move_number = -1
        # Iterate over the history, constructing SGF move strings.
        # Skip the first history state (the initial board, no move)
        # Make sure the current state is at the end.
        game.history.append(game.current_state)
        for pstate in game.history[1:]:
            state = pickle.loads(pstate)
            whose_move = state.get_whose_move()
            assert whose_move in [CONST.Black_Color, CONST.White_Color]

            # Set the move number, if necessary.
            if state.get_current_move_number() != move_number + 1:
                move_number_str = "MN[%d]" % state.get_current_move_number()
            else:
                move_number_str = ""
            move_number = state.get_current_move_number()

            # Encode the move.
            if state.get_last_move_was_pass():
                moves.append("%s%s[]" % (move_number_str, mover[whose_move]))
            else:
                moves.append("%s%s[%s]" % (move_number_str, mover[whose_move], pos_to_coord(state.get_last_move())))

        items = {
            'base_url': AppEngineHelper.base_url(),
            'start_date': game.date_created.date().isoformat(),
            'stop_date': game.date_last_moved.date().isoformat(),
            'board_size': board.get_width(),
            'komi': board.get_komi(),
            'handicap': handicap,
            'handicap_stones': handicap_stones,
            'white_name': white_player.get_friendly_name(),
            'black_name': black_player.get_friendly_name(),
            'moves': moves,
        }

        self.render_template("game.sgf", items, 'application/x-go-sgf')

        
#------------------------------------------------------------------------------
# Main WebApp Code
#------------------------------------------------------------------------------

def main():
    url_map = [
        ('/get-going/', GetGoingHandler),
        ('/play/([-\w]+)/', PlayGameHandler),
        ('/history/([-\w]+)/', HistoryHandler),
        ('/history/([-\w]+)\.sgf', SGFHandler),
        ('/options/([-\w]+)/', OptionsHandler),
        ('/service/create-game/', CreateGameHandler),
        ('/service/make-this-move/', MakeThisMoveHandler),
        ('/service/has-opponent-moved/', HasOpponentMovedHandler),
        ('/service/change-options/', ChangeOptionsHandler),
        ('/service/pass/', PassHandler),
        ('/service/resign/', ResignHandler),
        ('/service/recent-chat/', RecentChatHandler),
        ('/service/add-chat/', AddChatHandler),
        ('/service/get-historical-state/', GetHistoricalStateHandler)
    ]
    
    application = webapp.WSGIApplication(url_map, debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
