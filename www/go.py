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
import webapp2
from datetime import datetime, timedelta
import simplejson
from StringIO import StringIO

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
    Komis = [6.5, 5.5, 0.5, -4.5, -5.5]
    Komi_Names = ['has six komi', 'has five komi', 'has no komi', 'has five reverse komi', 'has six reverse komi']
    Komi_None = 2
    Email_Contact = "email"
    Twitter_Contact = "twitter"
    No_Contact = "none"
    Default_Email = "nobody@example.com"

    # "I" is purposfully skipped because, historically, people got confused between "I" and "J"
    Column_Names = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T"]

def handicap_position(stone, handicap, size_index, version):
    # Placement of the centre stone was changed in version 1.
    if version >= 1 and stone >= 4 and (handicap == 6 or handicap == 8):
        # If the handicap is 6 or 8, skip the centre stone.
        return CONST.Handicap_Positions[size_index][stone + 1]
    else:
        return CONST.Handicap_Positions[size_index][stone]

def handicap_positions(handicap, size_index, version):
    return [handicap_position(i, handicap, size_index, version) for i in range(handicap)]

def opposite_color(color):
    return 3 - color

def pos_to_coord(pos):
    """Convert a position into letter coordinates, for SGF"""
    x, y = pos
    return "%s%s" % (string.letters[x], string.letters[y])


#------------------------------------------------------------------------------
# Exception Handling & AppEngine Helpers
#------------------------------------------------------------------------------

# Work around dev_appserver limitations (stdout goes to browser.)
def BREAKPOINT():
    import pdb
    p = pdb.Pdb(None, sys.__stdin__, sys.__stdout__)
    p.set_trace()

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
# Hack to patch module changes when moving to the python2.7 API
#------------------------------------------------------------------------------

_pickle_module_name_map = {
    '__main__': 'go',
    'GameState': 'GameState',
}

def _pickle_map_name(name):
    return _pickle_module_name_map.get(name, name)

def _pickle_dispatch_global(self):
    module = _pickle_map_name(self.readline()[:-1])
    name = _pickle_map_name(self.readline()[:-1])
    klass = self.find_class(module, name)
    self.append(klass)

def safe_pickle_loads(s):
    f = StringIO(s)
    unpickler = pickle.Unpickler(f)
    unpickler.dispatch[pickle.GLOBAL] = _pickle_dispatch_global
    return unpickler.load()


#------------------------------------------------------------------------------
# Game State
#------------------------------------------------------------------------------

import array
import itertools
class BoardArray(object):
    def __init__(self, width=19, height=19, default=0, typecode='i'):
        self.width = width
        self.height = height
        self.board = array.array(typecode, itertools.repeat(default, width * height))

    def index(self, x, y):
        assert (0 <= x) and (x < self.width)
        assert (0 <= y) and (y < self.height)
        return y * self.height + x

    def get(self, x, y):
        return self.board[self.index(x, y)]

    def set(self, x, y, value):
        self.board[self.index(x, y)] = value

class GameBoard(object):
    def __init__(self, board_size_index=0, handicap_index=0, komi_index=0):
        super(GameBoard, self).__init__()
        self.width = CONST.Board_Sizes[board_size_index][0]
        self.height = CONST.Board_Sizes[board_size_index][1]
        self.size_index = board_size_index
        self.handicap_index = handicap_index

        # v1: access via get_version.
        self._version = 3

        # v2: access via get_komi_index.
        self._komi_index = komi_index

        # v3: access via has_owners.
        self._has_owners = False

        self._make_board()
        self._apply_handicap()

    def _make_board(self):
        self.board = []
        for x in range(self.width):
            self.board.append([CONST.No_Color] * self.height)

    def make_owners(self):
        self.owners = []
        for x in range(self.width):
            self.owners.append([CONST.No_Color] * self.height)
        self._has_owners = True

    def _apply_handicap(self):
        positions_handicap = self.get_handicap_positions()

        for i in range(self.get_handicap()):
            self.set(positions_handicap[i][0], positions_handicap[i][1], CONST.Black_Color)

    def get(self, x, y):
        return self.board[x][y]

    def set(self, x, y, color):
        self.board[x][y] = color

    def get_owner(self, x, y):
        if self.has_owners():
            return self.owners[x][y]
        else:
            # Until the final game state, nothing is owned by either player.
            return CONST.No_Color

    def set_owner(self, x, y, color):
        if not self.has_owners():
            # Created on demand to reduce size of Game.history.
            self.make_owners();
        self.owners[x][y] = color

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_size_index(self):
        return self.size_index

    def get_handicap_positions(self):
        return handicap_positions(self.get_handicap(), self.size_index, self.get_version())

    def get_version(self):
        # Since "_version" is new, it won't exist for old game pickles.
        try:
            return self._version
        except Exception:
            return 0

    def has_owners(self):
        if self.get_version() >= 3:
            return self._has_owners
        else:
            # Even with boards before v3, _has_owners may be 'True'.
            try:
                return self._has_owners
            except Exception:
                return False

    def get_column_names(self):
        return CONST.Column_Names[:self.width]

    def get_row_names(self):
        row_names = []
        for i in range(self.height, 0, -1):
            row_names.append(str(i))
        return row_names

    def get_komi_index(self):
        if self.get_version() >= 2:
            return self._komi_index
        elif self.handicap_index:
            return CONST.Komi_None
        else:
            return 0

    def get_komi(self):
        return CONST.Komis[self.get_komi_index()]

    def get_handicap(self):
        return CONST.Handicaps[self.handicap_index]

    def get_state_string(self):
        # Used for passing the board state via javascript. Smallish.
        bs = ""
        for y in range(self.height):
            for x in range(self.width):
                piece = self.get(x, y)
                owner = self.get_owner(x, y)
                if piece == CONST.Black_Color:
                    if owner == CONST.White_Color:
                        bs += "c" # dead stone
                    else:
                        bs += "b"
                elif piece == CONST.White_Color:
                    if owner == CONST.Black_Color:
                        bs += "x" # dead stone
                    else:
                        bs += "w"
                else:
                    if owner == CONST.Black_Color:
                        bs += "B" # black territory
                    elif owner == CONST.White_Color:
                        bs += "W" # white territory
                    else:
                        bs += "."
        return bs

    def is_in_bounds(self, x, y):
        return (x >= 0) and (x < self.get_width()) and (y >= 0) and (y < self.get_height())

    def is_stone_in_suicide(self, x, y):
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
        liberties.append(self._compute_liberties_at(x - 1, y, other))
        liberties.append(self._compute_liberties_at(x, y - 1, other))
        liberties.append(self._compute_liberties_at(x + 1, y, other))
        liberties.append(self._compute_liberties_at(x, y + 1, other))

        ataris = 0
        captures = []

        # determine ataris and first pass on captured
        # (there may be duplicate captured stones at first)
        for count, connected in liberties:
            if count == 1:
                ataris += 1
            if count == 0:
                captures.append(connected)

        # flatten all captured stones into one (duplicate-free) batch
        final_captures = []
        for capture in captures:
            for x, y in capture:
                # Remove duplicates (n^2 operation but shouldn't be bad in even extreme go cases)
                if (x, y) not in final_captures:
                    final_captures.append((x, y))

        return (ataris, final_captures)

    def is_stone_of_color(self, x, y, color):
        if color == CONST.Both_Colors:
            return self.get(x, y) != CONST.No_Color
        return color == self.get(x, y)

    def is_alive(self, x, y, color=CONST.Both_Colors):
        if self.get_owner(x, y) == CONST.No_Color:
            return self.is_stone_of_color(x, y, color)
        return False

    def is_dead(self, x, y, color=CONST.Both_Colors):
        if self.get_owner(x, y) == CONST.No_Color:
            return False
        return self.is_stone_of_color(x, y, color)

    def compute_changed_stones(self, start_x, start_y):
        # "color" is the color that will die (or come back to life).
        color = self.get(start_x, start_y)
        other_color = opposite_color(color)

        # Do a depth-first search.
        def add_stone_to_queue(is_in_bounds, visited, queue, x, y):
            if is_in_bounds(x, y) and visited.get(x, y) == 0:
                visited.set(x, y, 1)
                queue.append((x, y))

        coords = []
        queue = []
        visited = BoardArray(width=self.width, height=self.height)
        add_stone_to_queue(self.is_in_bounds, visited, queue, start_x, start_y)
        while len(queue):
            x, y = queue.pop()
            if not self.is_alive(x, y, other_color):
                if self.get(x, y) == color:
                    coords.append((x, y))
                add_stone_to_queue(self.is_in_bounds, visited, queue, x + 1, y)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x - 1, y)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x, y + 1)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x, y - 1)

        return coords

    def search_for_owner(self, start_x, start_y):
        found_black = False
        found_white = False

        # Do a depth-first search.
        def add_stone_to_queue(is_in_bounds, visited, queue, x, y):
            if is_in_bounds(x, y) and visited.get(x, y) == 0:
                visited.set(x, y, 1)
                queue.append((x, y))

        coords = []
        queue = []
        visited = BoardArray(width=self.width, height=self.height)
        add_stone_to_queue(self.is_in_bounds, visited, queue, start_x, start_y)
        while len(queue):
            x, y = queue.pop()
            if self.is_alive(x, y, CONST.Black_Color):
                found_black = True
            elif self.is_alive(x, y, CONST.White_Color):
                found_white = True
            else:
                coords.append((x, y))
                add_stone_to_queue(self.is_in_bounds, visited, queue, x + 1, y)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x - 1, y)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x, y + 1)
                add_stone_to_queue(self.is_in_bounds, visited, queue, x, y - 1)

        owner = CONST.No_Color
        if found_black and not found_white:
            owner = CONST.Black_Color
        elif found_white and not found_black:
            owner = CONST.White_Color

        return coords, owner

    def mark_territory(self):
        assert CONST.No_Color < 4
        assert CONST.White_Color < 4
        assert CONST.Black_Color < 4

        status = BoardArray(width=self.width, height=self.height)

        # Initialize "status" to have boundaries of live stones.
        found_live_stones = False
        found_dead_stones = False
        for x in range(self.width):
            for y in range(self.height):
                if self.is_alive(x, y):
                    status.set(x, y, self.get(x, y))
                    found_live_stones = True
                else:
                    status.set(x, y, CONST.No_Color)
                    if not found_dead_stones and self.is_dead(x, y):
                        found_dead_stones = True

        if found_dead_stones and not found_live_stones:
            # It doesn't make sense that every stone is dead.  Resurrect all of
            # them.
            for x in range(self.width):
                for y in range(self.height):
                    self.set_owner(x, y, CONST.No_Color)
                    status.set(x, y, self.get(x, y))

        # Find the territories, and save the corresponding owners.
        for x in range(self.width):
            for y in range(self.height):
                if status.get(x, y) == CONST.No_Color:
                    coords, owner = self.search_for_owner(x, y)
                    for a, b in coords:
                        status.set(a, b, owner + 4)

        # Set the calculated owners.
        for x in range(self.width):
            for y in range(self.height):
                owner = status.get(x, y)
                if owner >= 4:
                    owner = owner - 4
                    if self.is_stone_of_color(x, y, owner):
                        self.set_owner(x, y, CONST.No_Color)
                    else:
                        self.set_owner(x, y, owner)

    def count_territory(self, color, captures=0):
        count = captures
        opposite = opposite_color(color)
        for x in range(self.width):
            for y in range(self.height):
                if self.get_owner(x, y) == color:
                    count = count + 1
                    if self.get(x, y) == opposite:
                        count = count + 1
        return count

    def count_white_territory(self, black_stones_captured):
        return self.count_territory(CONST.White_Color, black_stones_captured) + self.get_komi()

    def count_black_territory(self, white_stones_captured):
        return self.count_territory(CONST.Black_Color, white_stones_captured)

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

        # Added in v3 of GameBoard.
        self.scoring_number = -1
        self.white_territory = 0
        self.black_territory = 0
        self.black_done_number = -1
        self.white_done_number = -1
        self.winner = CONST.No_Color

    def get_board(self):
        return self.board

    def get_version(self):
        return self.get_board().get_version()

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

    def get_scoring_number(self):
        if self.get_version() < 3:
            try:
                return self.scoring_number
            except Exception:
                # Need to support old games that enter the scoring stage.
                return -1
        else:
            return self.scoring_number

    def increment_scoring_number(self):
        if self.get_version() < 3:
            try:
                self.scoring_number += 1
            except Exception:
                # Need to support old games that enter the scoring stage.
                self.scoring_number = 0
                self.white_done_number = -1
                self.black_done_number = -1
                self.white_territory = 0
                self.black_territory = 0
        else:
            self.scoring_number += 1

    def has_scoring_data(self):
        return self.get_scoring_number() >= 0

    def is_white_done_scoring(self):
        # Order matters here, since we're relying on a short circuit.
        return self.has_scoring_data() and self.white_done_number == self.get_scoring_number()

    def is_black_done_scoring(self):
        # Order matters here, since we're relying on a short circuit.
        return self.has_scoring_data() and self.black_done_number == self.get_scoring_number()

    def is_done_scoring(self, color=CONST.Both_Colors):
        if color == CONST.White_Color:
            return self.is_white_done_scoring()
        elif color == CONST.Black_Color:
            return self.is_black_done_scoring()
        else:
            return self.is_white_done_scoring() and self.is_black_done_scoring()

    def set_done_scoring(self, color):
        if color == CONST.White_Color:
            self.white_done_number = self.get_scoring_number()
        elif color == CONST.Black_Color:
            self.black_done_number = self.get_scoring_number()

    def get_winner(self):
        if self.get_version() < 3:
            try:
                return self.winner
            except Exception:
                return CONST.No_Color
        else:
            return self.winner

    def is_winner(self, color):
        return color == self.get_winner()

    def set_winner(self, color):
        self.winner = color

    def get_white_territory(self):
        if self.has_scoring_data():
            return self.white_territory
        else:
            return -1

    def set_white_territory(self, territory):
        self.white_territory = territory

    def get_black_territory(self):
        if self.has_scoring_data():
            return self.black_territory
        else:
            return -1

    def set_black_territory(self, territory):
        self.black_territory = territory

    def count_territory(self):
        board = self.get_board()
        self.set_black_territory(board.count_black_territory(self.get_white_stones_captured()))
        self.set_white_territory(board.count_white_territory(self.get_black_stones_captured()))

    def get_last_move_message(self):
        return self.last_move_message

    def set_last_move_message(self, message):
        self.last_move_message = message

    def get_current_move_number(self):
        return self.current_move_number

    def set_current_move_number(self, number):
        self.current_move_number = number

    def increment_current_move_number(self, by=1):
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

        # Added in v3 of GameBoard.
        if self.has_scoring_data():
            clone.scoring_number = self.scoring_number
            clone.white_territory = self.white_territory
            clone.black_territory = self.black_territory
            clone.black_done_number = self.black_done_number
            clone.white_done_number = self.white_done_number

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
            if (x - 1) >= 0:
                left = self.board.get(x - 1, y)
                if left == self.color and not self.reached[x - 1][y]:
                    q.append((x - 1, y))

            # top
            if (y - 1) >= 0:
                top = self.board.get(x, y - 1)
                if top == self.color and not self.reached[x][y - 1]:
                    q.append((x, y - 1))

            # right
            if (x + 1) < self.board.get_width():
                right = self.board.get(x + 1, y)
                if right == self.color and not self.reached[x + 1][y]:
                    q.append((x + 1, y))

            # bottom
            if (y + 1) < self.board.get_height():
                bottom = self.board.get(x, y + 1)
                if bottom == self.color and not self.reached[x][y + 1]:
                    q.append((x, y + 1))

        # force a canoncial order for connected stones
        # so that we can determine if two sets of
        # connected stones are the same
        self.connected_stones.sort()

    def _get_liberty_count_at(self, x, y, w, h, already_counted):
        libs = 0

        # left liberty?
        if (x - 1) >= 0:
            left = self.board.get(x - 1, y)
            if left == CONST.No_Color and not already_counted[x - 1][y]:
                libs += 1
                already_counted[x - 1][y] = True

        # top liberty?
        if (y - 1) >= 0:
            top = self.board.get(x, y - 1)
            if top == CONST.No_Color and not already_counted[x][y - 1]:
                libs += 1
                already_counted[x][y - 1] = True

        # right liberty?
        if (x + 1) < w:
            right = self.board.get(x + 1, y)
            if right == CONST.No_Color and not already_counted[x + 1][y]:
                libs += 1
                already_counted[x + 1][y] = True

        # bottom liberty?
        if (y + 1) < h:
            bottom = self.board.get(x, y + 1)
            if bottom == CONST.No_Color and not already_counted[x][y + 1]:
                libs += 1
                already_counted[x][y + 1] = True

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
    def notify_your_turn(your_name, your_email, your_cookie, opponent_name, opponent_email, move_message, move_number):
        your_address = EmailHelper._rfc_address(your_name, your_email)

        message = mail.EmailMessage()
        message.sender = EmailHelper.No_Reply_Address
        message.subject = "[GO - Move #%s] It's your turn against %s" % (str(move_number), opponent_name)
        message.to = your_address

        if move_message == "It's your turn to move.":
            # TODO UNHACK -- ugly, but I'm too lazy to do this well at the moment.
            email_body = "It's your turn to make a move against %s." % opponent_name
        else:
            email_body = move_message
        email_body += " Just follow this link:\n\n%s\n" % EmailHelper._game_url(your_cookie)
        message.body = email_body

        message.send()

    @staticmethod
    def notify_scoring(your_name, your_email, your_cookie, opponent_name, opponent_email, you_are_done=False, no_longer_done=False, game_over=False):
        your_address = EmailHelper._rfc_address(your_name, your_email)

        message = mail.EmailMessage()
        message.sender = EmailHelper.No_Reply_Address
        message.to = your_address
        message.subject = "[GO - Scoring] Scoring against %s" % opponent_name

        if game_over:
            email_body = "The game is over!"
        elif no_longer_done:
            email_body = "%s has continued scoring; you are no longer finished." % opponent_name
        elif you_are_done:
            email_body = "%s has finished scoring; you should do the same." % opponent_name
        else:
            email_body = "It's time to score your game against %s." % opponent_name
        email_body += " Just follow this link:\n\n%s\n" % EmailHelper._game_url(your_cookie)
        message.body = email_body

        message.send()

    @staticmethod
    def remind_player(player_name, player_email, player_cookie, opponent_name, move_number, is_scoring):
        player_address = EmailHelper._rfc_address(player_name, player_email)
        message = mail.EmailMessage()
        message.sender = EmailHelper.No_Reply_Address
        message.to = player_address
        if is_scoring:
            message.subject = "[GO - Scoring] REMINDER: You are still scoring your game against %s" % (str(move_number), opponent_name)
            message.body = "Just a reminder that you are still scoring in your game against %s. You haven't done anything in over a week. To mark dead stones or finish the game, just follow this link:\n\n%s\n" % (opponent_name, EmailHelper._game_url(player_cookie))
        else:
            message.subject = "[GO - Move #%s] REMINDER: It's still your turn against %s" % (str(move_number), opponent_name)
            message.body = "Just a reminder that it's still your turn to move against %s. Your last move was over a week ago. To make a move, just follow this link:\n\n%s\n" % (opponent_name, EmailHelper._game_url(player_cookie))
        message.send()


#------------------------------------------------------------------------------
# Twitter Support
#------------------------------------------------------------------------------

class TwitterBuffer(object):
    def __init__(self, text):
        super(TwitterBuffer, self).__init__()
        self._text = text

    def read(self):
        return self._text

class TwitterHelper(object):
    @staticmethod
    def _open_basic_auth_url(username, password, url, params):
        # The "right" way to do this with urllib2 sucks. Why bother?
        data = None
        if params is not None:
            data = urllib.urlencode(params)
        # BREAKPOINT()
        req = urllib2.Request(url, data)
        base64string = base64.encodestring('%s:%s' % (username, password))[:-1]
        authheader = "Basic %s" % base64string
        req.add_header("Authorization", authheader)
        try:
            handle = urllib2.urlopen(req)
        except urllib2.HTTPError, e:
            raw_message = e.read()
            message = raw_message
            try:
                message = simplejson.loads(message)[u'error']
            except:
                pass
            logging.warn("Got HTTP %d during twitter request for URL %s: %s" % (e.code, url, message))
            # HACK HACK HACK to get around the new (and, I think, bad) change to the twitter API
            # that causes an HTTP 403 (forbidden) to get returned on friendship creation
            # IF you're already following that person. 403 seems like the wrong answer, and it
            # screws up the design of my code...
            if (e.code == 403) and ('friendships/create' in url):
                return TwitterBuffer(raw_message)
            else:
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
        if not isinstance(result, bool):
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
        return TwitterHelper._make_boolean_twitter_call("http://twitter.com/friendships/exists.json?user_a=%s&user_b=%s" % (a, b), None)

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
        # NOTE: WAS _make_success_twitter_call_as, but they changed the API -- you now get a HTTP 403 when you attempt to follow someone you're already following.
        return TwitterHelper._make_twitter_call_as("http://twitter.com/friendships/create/%s.json?follow=true" % b, {"ignore": "this"}, a, a_password)

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

    @staticmethod
    def notify_scoring(your_name, your_twitter, your_cookie, opponent_name, game_over=False):
        if game_over:
            message = "The game is over!"
        else:
            message = "It's your turn to score against %s." % TwitterHelper._trim_name(opponent_name)
        message += " " + TwitterHelper._game_url(your_cookie)
        return TwitterHelper.send_notification_to_user(your_twitter, message)

    @staticmethod
    def remind_player(player_name, player_twitter, player_cookie, is_scoring):
        if is_scoring:
            message = "Just a reminder: you're still scoring; you haven't done anything in over a week. %s" % TwitterHelper._game_url(player_cookie)
        else:
            message = "Just a reminder: it's still your turn to move; you haven't moved in over a week. %s" % TwitterHelper._game_url(player_cookie)
        return TwitterHelper.send_notification_to_user(player_twitter, message)

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
    date_created = db.DateTimeProperty(auto_now=False)
    date_last_moved = db.DateTimeProperty(auto_now=False)
    history = db.ListProperty(db.Blob)
    current_state = db.BlobProperty()

    # Back reference the players
    black_cookie = db.StringProperty()
    white_cookie = db.StringProperty()

    # Recent chat
    chat_history = db.ListProperty(db.Blob)

    is_finished = db.BooleanProperty(default=False)
    has_scoring_data = db.BooleanProperty(default=False)
    reminder_send_time = db.DateTimeProperty(auto_now=False)

    def get_black_player(self):
        return ModelCache.player_by_cookie(self.black_cookie)

    def get_white_player(self):
        return ModelCache.player_by_cookie(self.white_cookie)

    def get_player_whose_move(self):
        if self.is_finished or self.has_scoring_data:
            return None
        whose_move = safe_pickle_loads(self.current_state).get_whose_move()
        if whose_move == CONST.Black_Color:
            return self.get_black_player()
        else:
            return self.get_white_player()

    def in_progress(self):
        return not self.has_scoring_data and not self.is_finished

    def is_scoring(self):
        return self.has_scoring_data and not self.is_finished

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

    def get_reminder_send_time(self):
        __reminder_send_time = None
        try:
            __reminder_send_time = self.reminder_send_time
        except:
            __reminder_send_time
        return __reminder_send_time

    def dont_remind_for_long_time(self):
        self.reminder_send_time = datetime.now() + timedelta(weeks=52)
        self.put()

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
    show_grid = db.BooleanProperty(default=False)

    def get_safe_show_grid(self):
        try:
            safe_show_grid = self.show_grid
        except:
            safe_show_grid = False
        return safe_show_grid

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

class GoHandler(webapp2.RequestHandler):
    def _template_path(self, filename):
        return os.path.join(os.path.dirname(__file__), 'templates', filename)

    def render_json(self, obj):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(simplejson.dumps(obj))

    def render_json_as_text(self, obj):
        self.response.headers['Content-Type'] = 'text/plain'
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
        # i_last = len(email) - 1 XXX what is this?

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
    def get(self, *args):
        self.render_template("get-going.html")


#------------------------------------------------------------------------------
# "Create Game" Handler
#------------------------------------------------------------------------------

class CreateGameHandler(GoHandler):
    def fail(self, flash="Invalid input."):
        self.render_json({'success': False, 'need_your_twitter_password': False, 'flash': flash})

    def require_twitter_password(self, flash):
        self.render_json({'success': True, 'need_your_twitter_password': True, 'flash': flash})

    def create_game(self, your_name, your_contact, your_contact_type, opponent_name, opponent_contact, opponent_contact_type, your_color, board_size_index, handicap_index, komi_index):
        # Create cookies for accessing the game
        your_cookie, opponent_cookie = GameCookie.unique_pair()

        # Create the game state and board blobs
        board = GameBoard(board_size_index, handicap_index, komi_index)
        state = GameState()
        state.set_board(board)
        state.whose_move = CONST.Black_Color if CONST.Handicaps[handicap_index] == 0 else CONST.White_Color

        # Create a game model instance
        game = Game()
        game.date_created = datetime.now()
        game.date_last_moved = datetime.now()
        game.reminder_send_time = datetime.now()
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
            komi_index = int(self.request.POST.get("komi_index"))
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

        if (komi_index < 0) or (komi_index >= len(CONST.Komis)):
            self.fail("Invalid komi.")
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
            your_cookie, your_turn = self.create_game(your_name, your_contact, your_contact_type, opponent_name, opponent_contact, opponent_contact_type, your_color, board_size_index, handicap_index, komi_index)
            self.success(your_cookie, your_turn)
        except:
            logging.error("An unexpected error occured in CreateGameHandler: %s" % ExceptionHelper.exception_string())
            self.fail("Sorry, an unexpected error occured. Please try again in a minute or two.")


#------------------------------------------------------------------------------
# "Not Your Turn" Handler
#------------------------------------------------------------------------------

class NotYourTurnHandler(GoHandler):
    def get(self, *args):
        self.render_template("not-your-turn.html")


#------------------------------------------------------------------------------
# "Play Game" Handler
#------------------------------------------------------------------------------

class PlayGameHandler(GoHandler):
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

        opponent_player = player.get_opponent()

        state = safe_pickle_loads(game.current_state)
        your_move = (state.whose_move == player.color)
        board = state.get_board()
        you_are_done_scoring = state.is_done_scoring(player.color)
        opponent_done_scoring = state.is_done_scoring(opponent_player.color)
        you_win = state.is_winner(player.color)
        opponent_wins = state.is_winner(opponent_player.color)
        by_resignation = (you_win or opponent_wins) and not state.has_scoring_data()

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
            'game_is_scoring': "true" if game.is_scoring() else "false",
            'game_is_scoring_python': game.is_scoring(),
            'you_are_done_scoring': "true" if you_are_done_scoring else "false",
            'you_are_done_scoring_python': you_are_done_scoring,
            'opponent_done_scoring': "true" if opponent_done_scoring else "false",
            'opponent_done_scoring_python': opponent_done_scoring,
            'scoring_number': state.get_scoring_number(),
            'game_is_finished': "true" if game.is_finished else "false",
            'game_is_finished_python': game.is_finished,
            'game_in_progress': "true" if game.in_progress() else "false",
            'game_in_progress_python': game.in_progress(),
            'any_captures': (state.get_black_stones_captured() + state.get_white_stones_captured()) > 0,
            'has_scoring_data': game.has_scoring_data,
            'black_territory': state.get_black_territory(),
            'white_territory': state.get_white_territory(),
            'you_win': "true" if you_win else "false",
            'you_win_python': you_win,
            'opponent_wins': "true" if opponent_wins else "false",
            'opponent_wins_python': opponent_wins,
            'by_resignation': "true" if by_resignation else "false",
            'by_resignation_python': by_resignation,
            'board_class': board.get_class(),
            'komi': board.get_komi(),
            'show_grid': "true" if player.get_safe_show_grid() else "false",
            'show_grid_python': player.get_safe_show_grid(),
            'row_names': board.get_row_names(),
            'column_names': board.get_column_names(),
            'board_width': board.get_width(),
            'board_height': board.get_height(),
        }

        self.render_template("play.html", items)


#------------------------------------------------------------------------------
# "Make This Move" Handler
#------------------------------------------------------------------------------

class MakeThisMoveHandler(GoHandler):
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

        state = safe_pickle_loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        try:
            current_move_number_str = self.request.POST.get("current_move_number")
            current_move_number = int(current_move_number_str)
        except:
            self.fail("Invalid current move number; refresh game board.")
            return

        if current_move_number != game.get_current_move_number():
            self.fail("Wrong move number; refresh stale game board.")
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

        # okay, now that we've handled captures, do we have a situation where this move would be suicidal?
        if new_board.is_stone_in_suicide(move_x, move_y):
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
            two_back_state = safe_pickle_loads(game.history[-1])
            two_back_board = two_back_state.get_board()
            two_back_state_string = two_back_board.get_state_string()
            if two_back_state_string == new_state_string:
                self.fail("Sorry, but this move would violate the <a href=\"http://www.samarkand.net/Academy/learn_go/learn_go_pg8.html\">rule of Ko</a>. Move somewhere else and try playing here later!")
                return

        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()
        game.reminder_send_time = datetime.now()

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email, move_message, new_state.get_current_move_number())
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
            'last_move_y': move_y,
        }

        self.render_json(items)


#------------------------------------------------------------------------------
# "Pass" Handler
#------------------------------------------------------------------------------

class PassHandler(GoHandler):
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

        state = safe_pickle_loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        try:
            current_move_number_str = self.request.POST.get("current_move_number")
            current_move_number = int(current_move_number_str)
        except:
            self.fail("Invalid current move number; refresh game board.")
            return

        if current_move_number != game.get_current_move_number():
            self.fail("Wrong move number; refresh stale game board.")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_board = new_state.get_board()

        new_state.increment_current_move_number()
        new_state.set_whose_move(opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        previous_also_passed = state.get_last_move_was_pass()

        if previous_also_passed:
            move_message = "Mark the dead stones. Click done when finished. When you and your opponent agree, the game will end."

            game.has_scoring_data = True
            new_state.increment_scoring_number()

            new_board.mark_territory()
            new_state.count_territory()
        else:
            move_message = "Your opponent passed. You can make a move, or you can pass again to end the game."
        new_state.set_last_move_message(move_message)

        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()
        game.reminder_send_time = datetime.now()

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email, move_message, new_state.get_current_move_number())
        elif opponent.does_want_twitter():
            TwitterHelper.notify_your_turn(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), move_message)

        items = {
            'success': True,
            'flash': 'OK',
            'current_move_number': game.get_current_move_number(),
            'board_state_string': new_board.get_state_string(),
            'white_territory': new_state.get_white_territory(),
            'black_territory': new_state.get_black_territory(),
            'scoring_number': new_state.get_scoring_number(),
            'game_is_scoring': game.is_scoring(),
            'game_is_finished': game.is_finished,
        }

        self.render_json(items)

#------------------------------------------------------------------------------
# "Mark Stone Dead/Alive" Handler
#------------------------------------------------------------------------------

class MarkStoneHandler(GoHandler):
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
            self.fail("No more stones can be marked dead; the game is finished.")
            return

        if game.in_progress():
            self.fail("Scoring is not allowed yet; the game is still in progress.")
            return

        state = safe_pickle_loads(game.current_state)

        if state.is_done_scoring(player.color):
            self.fail("Sorry, but you have already finished scoring.")
            return

        board = state.get_board()
        try:
            stone_x = int(self.request.POST.get("stone_x"))
            stone_y = int(self.request.POST.get("stone_y"))
            owner = int(self.request.POST.get("owner"))
        except:
            self.fail("Invalid scoring x/y coordinate.")
            return

        if (stone_x < 0) or (stone_x >= board.get_width()) or (stone_y < 0) or (stone_y >= board.get_height()):
            self.fail("Stone coordinates are out-of-bounds.")
            return

        piece_at = board.get(stone_x, stone_y)
        owner_at = board.get_owner(stone_x, stone_y)
        if piece_at == CONST.No_Color:
            self.fail("You can't mark an empty coordinate as dead or alive!")
            return
        elif owner == piece_at:
            color = CONST.Color_Names[piece_at]
            self.fail("Unexpected error: " + color + " stone cannot be " + color + " territory.")
            return
        elif owner == owner_at:
            # TODO failing maybe doesn't make sense here.  What does?
            self.fail("Unexpected error: stone already marked as suggested.")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_board = new_state.get_board()

        # Increment the scoring number.
        new_state.increment_scoring_number()

        # Deal with other dead/alive stones.
        stones = new_board.compute_changed_stones(stone_x, stone_y)

        if (stone_x, stone_y) not in stones:
            # Should at least include the stone being marked!
            self.fail("Unexpected error: marking stone had no effect.")
            return

        for x, y in stones:
            new_board.set_owner(x, y, owner)

        new_board.mark_territory()
        new_state.count_territory()

        # Replace the current game state.
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.reminder_send_time = datetime.now()
        new_state_string = new_board.get_state_string()

        try:
            game.put()
        except:
            game.put()

        opponent = player.get_opponent()
        was_done_scoring = state.is_done_scoring(opponent.color)

        if was_done_scoring:
            # Send an email to the opponent.
            if opponent.wants_email:
                EmailHelper.notify_scoring(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email, no_longer_done=True)
            elif opponent.does_want_twitter():
                TwitterHelper.notify_scoring(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), no_longer_done=True)

        items = {
            'success': True,
            'flash': 'TODO',
            'white_territory': new_state.get_white_territory(),
            'black_territory': new_state.get_black_territory(),
            'scoring_number': new_state.get_scoring_number(),
            'board_state_string': new_state_string,
        }

        self.render_json(items)

#------------------------------------------------------------------------------
# "Done" Handler
#------------------------------------------------------------------------------

class DoneHandler(GoHandler):
    def fail(self, message):
        self.render_json({'success': False, 'flash': message})

    def post(self, *args):
        cookie = self.request.POST.get("your_cookie")
        if not cookie:
            self.fail("Unexpected error: no cookie found.")
            return

        try:
            done_scoring_number = int(self.request.POST.get("scoring_number"))
        except:
            self.fail()
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
            self.fail("The game is already finished.")
            return
        if game.in_progress():
            self.fail("The game has not started scoring yet.")
            return

        state = safe_pickle_loads(game.current_state)
        if state.is_done_scoring(player.color):
            self.fail("You have already finished scoring.")
            return

        if state.get_scoring_number() != done_scoring_number:
            if state.is_done_scoring(player.color):
                # Weird... must have two windows open or something.
                self.render_success(game, player, state, 'OK')
            else:
                self.render_success(game, player, state, 'Something has changed; review before clicking done.')
            return

        # Mark the player as done.
        new_state = state.clone()
        new_state.set_done_scoring(player.color)

        if new_state.is_done_scoring():
            game.is_finished = True
            move_message = "The game is over!"
            new_state.set_last_move_message(move_message)

            # Calculate the winner.  Tie goes to white.
            if new_state.white_territory >= new_state.black_territory:
                new_state.set_winner(CONST.White_Color)
            else:
                new_state.set_winner(CONST.Black_Color)

        game.reminder_send_time = datetime.now()
        game.current_state = db.Blob(pickle.dumps(new_state))

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_scoring(
                opponent.get_friendly_name(),
                opponent.email, opponent.cookie,
                player.get_friendly_name(), player.email,
                you_are_done=True, game_over=game.is_finished)
        elif opponent.does_want_twitter():
            TwitterHelper.notify_scoring(
                opponent.get_friendly_name(),
                opponent.twitter, opponent.cookie,
                player.get_friendly_name(),
                game_over=game.is_finished)

        self.render_success(game, player, new_state, 'OK')

    def render_success(self, game, player, state, flash):
        opponent = player.get_opponent()
        board = state.get_board()
        items = {
            'success': True,
            'flash': flash,
            'board_state_string': board.get_state_string(),
            'you_are_done_scoring': state.is_done_scoring(player.color),
            'opponent_done_scoring': state.is_done_scoring(opponent.color),
            'white_territory': state.get_white_territory(),
            'black_territory': state.get_black_territory(),
            'scoring_number': state.get_scoring_number(),
            'you_win': state.is_winner(player.color),
            'opponent_wins': state.is_winner(opponent.color),
            'game_is_finished': game.is_finished,
        }

        self.render_json(items)

#------------------------------------------------------------------------------
# "Resign" Handler
#------------------------------------------------------------------------------

class ResignHandler(GoHandler):
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

        state = safe_pickle_loads(game.current_state)
        if state.whose_move != player.color:
            self.fail("Sorry, but it is not your turn.")
            return

        try:
            current_move_number_str = self.request.POST.get("current_move_number")
            current_move_number = int(current_move_number_str)
        except:
            self.fail("Invalid current move number; refresh game board.")
            return

        if current_move_number != game.get_current_move_number():
            self.fail("Wrong move number; refresh stale game board.")
            return

        # Create the potentially new state
        new_state = state.clone()
        new_state.increment_current_move_number()
        new_state.set_whose_move(opposite_color(player.color))
        new_state.set_last_move_was_pass(True)

        move_message = "The game is over!"
        game.is_finished = True
        new_state.set_winner(opposite_color(player.color))
        new_state.set_last_move_message(move_message)

        game.history.append(game.current_state)
        game.current_state = db.Blob(pickle.dumps(new_state))
        game.date_last_moved = datetime.now()
        game.reminder_send_time = datetime.now()

        try:
            game.put()
        except:
            game.put()

        # Send an email, but only if they want it.
        opponent = player.get_opponent()
        if opponent.wants_email:
            EmailHelper.notify_your_turn(opponent.get_friendly_name(), opponent.email, opponent.cookie, player.get_friendly_name(), player.email, move_message, new_state.get_current_move_number())
        elif opponent.does_want_twitter():
            TwitterHelper.notify_your_turn(opponent.get_friendly_name(), opponent.twitter, opponent.cookie, player.get_friendly_name(), move_message)


        items = {
            'success': True,
            'flash': 'OK',
            'current_move_number': game.get_current_move_number(),
            'game_is_scoring': game.is_scoring(),
            'game_is_finished': game.is_finished,
        }

        self.render_json(items)


#------------------------------------------------------------------------------
# "Has Opponent Moved" Handler
#------------------------------------------------------------------------------

class HasOpponentMovedHandler(GoHandler):
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

        state = safe_pickle_loads(game.current_state)
        if state.whose_move != player.color:
            self.render_json({'success': True, 'flash': 'OK', 'has_opponent_moved': False})
        else:
            board = state.get_board()
            opponent = player.get_opponent()
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
                'white_territory': state.get_white_territory(),
                'black_territory': state.get_black_territory(),
                'scoring_number': state.get_scoring_number(),
                'you_win': state.is_winner(player.color),
                'opponent_wins': state.is_winner(opponent.color),
                'game_is_scoring': game.is_scoring(),
                'game_is_finished': game.is_finished})

#------------------------------------------------------------------------------
# "Has Opponent Scored" Handler
#------------------------------------------------------------------------------

class HasOpponentScoredHandler(GoHandler):
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

        if game.in_progress():
            self.fail("Scoring is not allowed yet; the game is still in progress.")
            return

        try:
            base_scoring_number = int(self.request.POST.get("scoring_number"))
        except:
            self.fail("Unexpected error: invalid scoring request")
            return

        state = safe_pickle_loads(game.current_state)

        if state.get_scoring_number() == base_scoring_number and not game.is_finished:
            self.render_json({'success': True, 'flash': 'OK', 'has_opponent_scored': False})
        else:
            board = state.get_board()
            opponent = player.get_opponent()
            self.render_json({
                'success': True,
                'flash': 'OK',
                'has_opponent_scored': True,
                'board_state_string': board.get_state_string(),
                'you_are_done_scoring': state.is_done_scoring(player.color),
                'opponent_done_scoring': state.is_done_scoring(opponent.color),
                'white_territory': state.get_white_territory(),
                'black_territory': state.get_black_territory(),
                'scoring_number': state.get_scoring_number(),
                'you_win': state.is_winner(player.color),
                'opponent_wins': state.is_winner(opponent.color),
                'game_is_finished': game.is_finished,
            })


#------------------------------------------------------------------------------
# "Options" Handler
#------------------------------------------------------------------------------

class OptionsHandler(GoHandler):
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
            'your_contact_type': player.get_active_contact_type(),
        }

        self.render_template("options.html", items)


#------------------------------------------------------------------------------
# "Change Options" Handler
#------------------------------------------------------------------------------

class ChangeOptionsHandler(GoHandler):
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
# "Change Grid Options" Handler
#------------------------------------------------------------------------------

class ChangeGridOptionsHandler(GoHandler):
    def fail(self, flash="Invalid input."):
        self.render_json({'success': False, 'flash': flash})

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
            show_grid_str = self.request.POST.get("show_grid").strip()

            # be stupidly restrictive in what we accept
            if show_grid_str == "true":
                show_grid = True
            elif show_grid_str == "false":
                show_grid = False
        except:
            show_grid = None

        if show_grid is None:
            self.fail("Unexpected error: invalid show_grid value.")
            return

        player.show_grid = show_grid
        try:
            player.put()
        except:
            player.put()
        ModelCache.clear_cookie(player.cookie)

        self.render_json({'success': True, 'flash': 'OK'})


#------------------------------------------------------------------------------
# "Recent Chat" Handler
#------------------------------------------------------------------------------

class RecentChatHandler(GoHandler):
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

        last_chat_seen = None
        try:
            last_chat_seen_str = self.request.POST.get("last_chat_seen")
            last_chat_seen = int(last_chat_seen_str)
        except:
            last_chat_seen = None
        if last_chat_seen is None:
            self.fail("Unexpected error: try refreshing your browser window.")
            return

        game = player.game
        if not game:
            self.fail("Unexpected error: couldn't find game for player.")
            return

        blob_history = game.get_chat_history_blobs()
        recent_blobs = blob_history[last_chat_seen:]
        # no longer desirable -- recent_blobs.reverse()
        recent_chats = []

        for blob in recent_blobs:
            entry = safe_pickle_loads(blob)
            recent_chats.append({'name': entry.get_player_friendly_name(), 'message': entry.get_message(), 'move_number': entry.get_move_number()})

        self.render_json({'success': True, 'flash': 'OK', 'chat_count': len(blob_history), 'recent_chats': recent_chats})


#------------------------------------------------------------------------------
# "Add Chat" Handler
#------------------------------------------------------------------------------

class AddChatHandler(GoHandler):
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

        state = safe_pickle_loads(game.current_state)

        # Message, etc.
        message = self.request.POST.get("message")
        if message is None:
            self.fail("Unexpected error: couldn't find game for player.")
            return

        message = message.strip()
        if len(message) > 140:
            message = message[:140] + '...'

        clean_message = cgi.escape(message)

        # Do nothing for empty messages
        if len(message) < 1:
            self.render_json({'success': True, 'no_message': True, 'flash': 'OK'})
            return

        last_chat_seen = None
        try:
            last_chat_seen_str = self.request.POST.get("last_chat_seen")
            last_chat_seen = int(last_chat_seen_str)
        except:
            last_chat_seen = None
        if last_chat_seen is None:
            self.fail("Unexpected error: try refreshing your browser window.")
            return

        # force game to have chat history
        blob_history = game.get_chat_history_blobs()
        entry = ChatEntry(cookie, clean_message, state.get_current_move_number())
        blob_history.append(db.Blob(pickle.dumps(entry)))
        game.chat_history = blob_history

        try:
            game.put()
        except:
            game.put()

        recent_blobs = blob_history[last_chat_seen:]
        # no longer desirable -- recent_blobs.reverse()
        recent_chats = []

        for blob in recent_blobs:
            entry = safe_pickle_loads(blob)
            recent_chats.append({'name': entry.get_player_friendly_name(), 'message': entry.get_message(), 'move_number': entry.get_move_number()})

        self.render_json({'success': True, 'flash': 'OK', 'chat_count': len(blob_history), 'recent_chats': recent_chats})


#------------------------------------------------------------------------------
# "History" Handler (for main history html page)
#------------------------------------------------------------------------------

class HistoryHandler(GoHandler):
    def fail(self, message):
        self.render_template("fail.html", {'message': message})

    def get(self, cookie, *args):
        self.get_move(cookie)

    def get_move(self, cookie, move=None):
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

        # XXX this appears unused
        # if player.color == CONST.Black_Color:
        #     opponent_player = white_player
        # else:
        #     opponent_player = black_player

        move_number = None
        if move:
            try:
                move_number = int(move)
            except:
                move_number = None

        max_move_number = len(game.history)
        requested_state = None
        if move_number is None or move_number >= max_move_number or move_number < 0:
            requested_state = game.current_state
        else:
            requested_state = game.history[move_number]

        state = safe_pickle_loads(requested_state)
        # XXX this appears unused your_move = (state.whose_move == player.color)
        board = state.get_board()

        last_move_x, last_move_y = state.get_last_move()

        items = {
            'your_cookie': cookie,
            'your_color': player.color,
            'board_size_index': board.get_size_index(),

            'board_state_string': board.get_state_string(),
            'white_stones_captured': state.get_white_stones_captured(),
            'black_stones_captured': state.get_black_stones_captured(),
            'current_move_number': state.current_move_number,
            'max_move_number': max_move_number,
            'last_move_message': state.get_last_move_message(),
            'last_move_x': last_move_x,
            'last_move_y': last_move_y,
            'last_move_was_pass': "true" if state.get_last_move_was_pass() else "false",
            'whose_move': state.whose_move,
            'white_name': white_player.get_friendly_name(),
            'black_name': black_player.get_friendly_name(),
            'board_class': board.get_class(),
            'you_are_black': player.color == CONST.Black_Color,
            'show_grid': "true" if player.get_safe_show_grid() else "false",
            'show_grid_python': player.get_safe_show_grid(),
            'row_names': board.get_row_names(),
            'column_names': board.get_column_names(),
            'board_width': board.get_width(),
            'board_height': board.get_height()
        }

        self.render_template("history.html", items)

class HistoryMoveHandler(HistoryHandler):
    def get(self, cookie, move, *args):
        self.get_move(cookie, move)

#------------------------------------------------------------------------------
# "Get Historical State" Handler
#------------------------------------------------------------------------------

class GetHistoricalStateHandler(GoHandler):
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
        max_move_number = len(game.history)
        if move_number >= max_move_number:
            requested_state = game.current_state
        elif (move_number >= 0) and (move_number < max_move_number):
            requested_state = game.history[move_number]
        else:
            self.fail("Unexpected error: move number is out of range.")
            return

        state = safe_pickle_loads(requested_state)

        board = state.get_board()
        last_move_x, last_move_y = state.get_last_move()

        self.render_json({
            'success': True,
            'flash': 'OK',
            'board_state_string': board.get_state_string(),
            'white_stones_captured': state.get_white_stones_captured(),
            'black_stones_captured': state.get_black_stones_captured(),
            'current_move_number': state.current_move_number,
            'max_move_number': max_move_number,
            'last_move_message': state.get_last_move_message(),
            'last_move_x': last_move_x,
            'last_move_y': last_move_y,
            'last_move_was_pass': state.get_last_move_was_pass(),
            'whose_move': state.whose_move})

#------------------------------------------------------------------------------
# "SGF" Handler (for SGF download)
#------------------------------------------------------------------------------

class SGFHandler(GoHandler):
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

        current_state = safe_pickle_loads(game.current_state)
        board = current_state.get_board()

        handicap = board.get_handicap()
        positions_handicap = board.get_handicap_positions()
        handicap_stones = [pos_to_coord(positions_handicap[i]) for i in range(board.get_handicap())]

        # Build a dict of all the games chat messages.
        chat_blobs = game.get_chat_history_blobs()
        chats = {}
        for blob in chat_blobs:
            entry = safe_pickle_loads(blob)
            move = entry.get_move_number()
            if move <= 0:
                move = 1
            move_chats = chats.get(move, [])
            move_chats.append("%s: %s" % (entry.get_player_friendly_name(), entry.get_message()))
            chats[move] = move_chats

        moves = []
        mover = " BW"
        move_number = -1
        # Iterate over the history, constructing SGF move strings.
        # Skip the first history state (the initial board, no move)
        # Make sure the current state is at the end.
        game.history.append(game.current_state)
        # Ensure we have the first move
        whose_move = safe_pickle_loads(game.history[0]).get_whose_move()
        for pstate in game.history[1:]:
            state = safe_pickle_loads(pstate)

            # Set the move number, if necessary.
            if state.get_current_move_number() != move_number + 1:
                move_number_str = "MN[%d]" % state.get_current_move_number()
            else:
                move_number_str = ""
            move_number = state.get_current_move_number()

            try:
                comment = "C[%s]" % "\n".join(chats[move_number])
            except KeyError:
                comment = ""

            # Encode the move.
            if state.get_last_move_was_pass():
                moves.append("%s%s[]%s" % (move_number_str, mover[whose_move], comment))
            else:
                moves.append("%s%s[%s]%s" % (move_number_str, mover[whose_move], pos_to_coord(state.get_last_move()), comment))

            # Color for next emitted move is based on whose turn
            # it is now.
            whose_move = state.get_whose_move()
            assert whose_move in [CONST.Black_Color, CONST.White_Color]

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
# Reminders!
#------------------------------------------------------------------------------

class EnsureReminderTimesHandler(GoHandler):
    def post(self, *args):
        # Grab some games and make sure that they each have a reminder_send_time set.
        # If not, set it!
        try:
            # get our request data
            try:
                last_id_seen = int(self.request.get('last_id_seen'))
            except:
                last_id_seen = 0

            try:
                amount = int(self.request.get('amount'))
            except:
                amount = 10

            # get some games -- if a key is specified, start there.
            if last_id_seen == 0:
                query = db.GqlQuery('SELECT * from Game ORDER BY __key__')
                games = query.fetch(amount)
            else:
                last_key_seen = db.Key.from_path('Game', last_id_seen)
                query = db.GqlQuery('SELECT * from Game WHERE __key__ > :1 ORDER BY __key__', last_key_seen)
                games = query.fetch(amount)

            # sanity check
            if games is None:
                self.render_json({'success': True, 'amount_found': 0, 'amount_modified': 0, 'new_last_id': -1})
            else:
                # figure out what the next key will be -- we've got to do
                # this stuff in batches, after all
                amount_found = len(games)
                if amount_found < 1:
                    last_item = None
                    new_last_id = -1
                else:
                    last_item = games[-1]
                    new_last_id = int(last_item.key().id())

                # batch up any games that are missing a key
                games_to_write = []
                for game in games:
                    rst = None
                    try:
                        rst = game.reminder_send_time
                    except:
                        rst = None
                    if rst is None:
                        dlm = game.date_last_moved
                        if dlm is None:
                            dlm = datetime.now()
                        game.reminder_send_time = dlm
                        games_to_write.append(game)

                if len(games_to_write) > 0:
                    try:
                        db.put(games_to_write)
                    except:
                        db.put(games_to_write)

                self.render_json({'success': True, 'amount_found': amount_found, 'amount_modified': len(games_to_write), 'new_last_id': new_last_id})
        except:
            self.render_json({'success': False, 'Error': ExceptionHelper.exception_string(), 'game_count': 0})

class UpdateDatabaseHandler(GoHandler):
    def get(self, *args):
        self.response.headers['Content-Type'] = "text/plain"
        self.render_template("update-database.html", {})

class SendRemindersHandler(GoHandler):
    def get(self, *args):
        # Handle one game at a time!
        # (TODO -- this code is ugly -- too many nested tests.)
        message = "No action taken."
        try:
            one_week_ago = datetime.now() - timedelta(weeks=1)
            two_months_ago = datetime.now() - timedelta(weeks=8)
            stale_game = db.GqlQuery("SELECT * FROM Game WHERE reminder_send_time < :1", one_week_ago).get()
            if (stale_game is None):
                message = "No stale games to remind about."
            else:
                if stale_game.is_finished:
                    stale_game.dont_remind_for_long_time()
                    message = "Found a finished 'stale' game. Ignoring."
                else:
                    if stale_game.date_last_moved < two_months_ago:
                        stale_game.dont_remind_for_long_time()
                        message = "Found a two-month-old 'stale' game. Giving up!"
                    else:
                        players = []

                        if stale_game.is_scoring():
                            black = stale_game.get_black_player()
                            white = stale_game.get_white_player()
                            for player in [black, white]:
                                if not stale_game.is_player_done_scoring(player):
                                    players.append(player)
                        else:
                            whose_move = stale_game.get_player_whose_move()
                            if whose_move is None:
                                stale_game.dont_remind_for_long_time()
                                message = "Found a 'stale' game with no current player. Was it finished? Hrm."
                            else:
                                players.append(whose_move)

                        for player in players:
                            if player.wants_email:
                                opponent = player.get_opponent()
                                state = safe_pickle_loads(stale_game.current_state)
                                EmailHelper.remind_player(player.get_friendly_name(), player.email, player.cookie, opponent.get_friendly_name(), state.get_current_move_number(), stale_game.is_scoring())
                                message = "Sent an email reminder to %s about game %s!" % (player.email, player.cookie)
                            elif player.does_want_twitter():
                                TwitterHelper.remind_player(player.get_friendly_name(), player.twitter, player.cookie, stale_game.is_scoring())
                                message = "Sent a twitter reminder to %s about game %s!" % (player.twitter, player.cookie)
                            else:
                                message = "Found 'stale' game %s that I couldn't notify about: player did not want notification." % player.cookie

                            stale_game.reminder_send_time = datetime.now()
                            stale_game.put()
        except:
            self.render_json_as_text({'success': False, 'Error': ExceptionHelper.exception_string(), 'message': message})
        else:
            self.render_json_as_text({'success': True, 'message': message})


#------------------------------------------------------------------------------
# Main WebApp Code
#------------------------------------------------------------------------------

url_map = [
    webapp2.Route(r'/get-going/', GetGoingHandler),
    webapp2.Route(r'/play/<:[-\w]+>/', PlayGameHandler),
    webapp2.Route(r'/history/<:[-\w]+>.sgf', SGFHandler),
    webapp2.Route(r'/history/<:[-\w]+>/', HistoryHandler),
    webapp2.Route(r'/history/<:[-\w]+>/<0|[1-9]\d*>/', HistoryMoveHandler),
    webapp2.Route(r'/options/<:[-\w]+>/', OptionsHandler),
    webapp2.Route(r'/service/create-game/', CreateGameHandler),
    webapp2.Route(r'/service/make-this-move/', MakeThisMoveHandler),
    webapp2.Route(r'/service/has-opponent-moved/', HasOpponentMovedHandler),
    webapp2.Route(r'/service/mark-stone/', MarkStoneHandler),
    webapp2.Route(r'/service/has-opponent-scored/', HasOpponentScoredHandler),
    webapp2.Route(r'/service/done/', DoneHandler),
    webapp2.Route(r'/service/change-options/', ChangeOptionsHandler),
    webapp2.Route(r'/service/change-grid-options/', ChangeGridOptionsHandler),
    webapp2.Route(r'/service/pass/', PassHandler),
    webapp2.Route(r'/service/resign/', ResignHandler),
    webapp2.Route(r'/service/recent-chat/', RecentChatHandler),
    webapp2.Route(r'/service/add-chat/', AddChatHandler),
    webapp2.Route(r'/service/get-historical-state/', GetHistoricalStateHandler),
    webapp2.Route(r'/cron/send-reminders/', SendRemindersHandler),
    webapp2.Route(r'/cron/ensure-reminder-times/', EnsureReminderTimesHandler),
    webapp2.Route(r'/cron/update-database/', UpdateDatabaseHandler)
]

application = webapp2.WSGIApplication(url_map, debug=True)


