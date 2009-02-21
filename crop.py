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


#-----
# This is a hack tool to help extract useful images from the wikimedia commons go pngs.

from PIL import Image

WH = 104
TL_CENTER = 63
OFFSET = TL_CENTER - (WH / 2)

def r(l,t):
    return ((l,t,l+WH,t+WH))

def offset(rect, x, y):
    l, t, r, b = rect
    return ((l+x, t+y, r+x, b+y))
    
def sq(x,y):
    try_r = r((x*WH) + OFFSET, (y*WH) + OFFSET)
    if (x == 18):
        try_r = offset(try_r, 3, 0)
    return try_r
    
def isq(board, x, y):
    return board.crop(sq(x,y))

def ssq(board, x, y, name):
    sq = isq(board, x, y)
    sq.save("%s-try.png" % name)    
    
board = Image.open("board-huge.png")
ssq(board, 0, 0, "tl")
ssq(board, 1, 0, "top")
ssq(board, 18, 0, "tr")

ssq(board, 0, 1, "left")
ssq(board, 1, 1, "center")
ssq(board, 18, 1, "right")

ssq(board, 0, 18, "bl")
ssq(board, 1, 18, "bottom")
ssq(board, 18, 18, "br")

ssq(board, 3, 3, "star")
