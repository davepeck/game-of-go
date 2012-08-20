/*

(c) 2009 Dave Peck, All Rights Reserved. (http://davepeck.org/)

This file is part of Dave Peck's Go.

Dave Peck's Go is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Dave Peck's Go is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with Dave Peck's Go.  If not, see <http://www.gnu.org/licenses/>.

*/


//-----------------------------------------------------------------------------
// Constants
//-----------------------------------------------------------------------------

var CONST = Class.create({});

CONST.No_Color = 0;
CONST.Black_Color = 1;
CONST.White_Color = 2;
CONST.Board_Sizes = [[19, 19], [13, 13], [9, 9]];
CONST.Star_Ordinals = [[3, 9, 15], [3, 6, 9], [2, 4, 6]];
CONST.Board_Size_Names = ['19 x 19', '13 x 13', '9 x 9'];
CONST.Handicaps = [0, 9, 8, 7, 6, 5, 4, 3, 2];
CONST.Handicap_Names = ['plays first', 'has a nine stone handicap', 'has an eight stone handicap', 'has a seven stone handicap', 'has a six stone handicap', 'has a five stone handicap', 'has a four stone handicap', 'has a three stone handicap', 'has a two stone handicap'];
CONST.Komis = [6.5, 5.5, 0.5, -4.5, -5.5];
CONST.Komi_Names = ['has six komi', 'has five komi', 'has no komi', 'has five reverse komi', 'has six reverse komi'];
CONST.Komi_None = 2;
CONST.Email_Contact = "email";
CONST.Twitter_Contact = "twitter";
CONST.No_Contact = "none";
CONST.Dim = "dim";
CONST.Notable = "notable";
CONST.Dangerous = "dangerous";
CONST.Board_Classes = ['nineteen_board', 'thirteen_board', 'nine_board'];

// "I" is purposfully skipped because, historically, people got confused between "I" and "J"
CONST.Column_Names = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T"];


//-----------------------------------------------------------------------------
// Helpers
//-----------------------------------------------------------------------------

function eval_json(text)
{
    return eval("(" + text + ")");
}

function hide(what)
{
    $(what).addClassName("hide");
}

function show(what)
{
    $(what).removeClassName("hide");
}

function seconds(num)
{
    return num * 1000;
}

function opposite_color(color)
{
    if (color == CONST.No_Color)
    {
        return color;
    }
    
    return 3 - color;
}

function set_selection_range(input, selection_start, selection_end)
{
    if (input.setSelectionRange)
    {
        input.focus();
        input.setSelectionRange(selection_start, selection_end);
    }
    else if (input.createTextRange)
    {
        var range = input.createTextRange();
        range.collapse(true);
        range.moveEnd('character', selection_end);
        range.moveStart('character', selection_start);
        range.select();
    }
    else
    {
        input.focus();
    }
}

function set_cursor_position(input, position)
{
    set_selection_range(input, position, position);
}

function fill_from_query_string(form)
{
    var query_params = window.location.search.toQueryParams();
    form.getInputs().each(function(input)
    {
        input.setValue(query_params[input.id]);
    });
}


//-----------------------------------------------------------------------------
// Validators
//-----------------------------------------------------------------------------

var ContactValidator = function() {}

ContactValidator.is_probably_good_email = function(s)
{
    if (!s || (s.length <= 4))
    {
        return false;
    }

    if (s.indexOf('@') == -1 || s.indexOf('.') == -1 || s.indexOf('@') == 0 || s.lastIndexOf('.') >= (s.length - 1) || (s.indexOf('@') >= s.lastIndexOf('.') - 1))
    {
        return false;
    }        

    return true;
}

ContactValidator.is_probably_good_twitter = function(s)
{
    if (!s || (s.length < 1) || (s.length > 16))
    {
        return false;
    }

    return s.match(/^[0-9a-zA-Z_]+$/);
}

ContactValidator.is_probably_good_contact = function(s, contact_type)
{
    if (contact_type == CONST.Email_Contact)
    {
        return ContactValidator.is_probably_good_email(s);
    }
    else
    {
        return ContactValidator.is_probably_good_twitter(s);
    }
}


//-----------------------------------------------------------------------------
// Game Start Handler
//-----------------------------------------------------------------------------

var GetGoing = Class.create({            
    initialize : function()
    {
        this.your_color = CONST.Black_Color;
        this.opponent_color = CONST.White_Color;
        this.board_size_index = 0;
        this.handicap_index = 0;
        this.handicap_id = "your_handicap";
        this.komi_index = 0;
        this.komi_id = "opponent_handicap";

        this.auto_komi = true;

        //We can't just assign the correct contact types, because the
        //HTML has a default that's updated by swapping.
        this.your_contact_type = CONST.Email_Contact;
        if (ContactValidator.is_probably_good_twitter(
                $F('your_contact')))
        {
            this.swap_your_contact_type();
        }
        this.opponent_contact_type = CONST.Email_Contact;
        if (ContactValidator.is_probably_good_twitter(
                $F('opponent_contact')))
        {
            this.swap_opponent_contact_type();
        }

        //Update validity flags
        this._input_your_name();
        this._input_your_contact();
        this._input_opponent_name();
        this._input_opponent_contact();

        this.showing_twitter_password = false;
        
        this._initialize_events();
    },

    swap_your_contact_type : function()
    {
        if (this.your_contact_type == CONST.Email_Contact)
        {
            this.your_contact_type = CONST.Twitter_Contact;
            $("your_contact_type").update("twitter");            
        }
        else
        {
            this.your_contact_type = CONST.Email_Contact;
            $("your_contact_type").update("email");
            this._hide_twitter_password();
        }
        this.valid_your_contact = ContactValidator.is_probably_good_contact($("your_contact").value, this.your_contact_type);        
        this._evaluate_validity();
    },

    swap_opponent_contact_type : function()
    {
        if (this.opponent_contact_type == CONST.Email_Contact)
        {
            this.opponent_contact_type = CONST.Twitter_Contact;
            $("opponent_contact_type").update("twitter");            
        }
        else
        {
            this.opponent_contact_type = CONST.Email_Contact;
            $("opponent_contact_type").update("email");
        }
        this.valid_opponent_contact = ContactValidator.is_probably_good_contact($("opponent_contact").value, this.opponent_contact_type);
        this._evaluate_validity();
    },
    
    swap_colors : function()
    {
        if (this.your_color == CONST.Black_Color)
        {
            this.your_color = CONST.White_Color;
            this.opponent_color = CONST.Black_Color;
            this.komi_id = "your_handicap";
            this.handicap_id = "opponent_handicap";
            $("your_color").update("white");
            $("your_color2").update("White");
            $("your_handicap").update(CONST.Komi_Names[this.komi_index]);
            $("opponent_color").update("black");            
            $("opponent_color2").update("Black");            
            $("opponent_handicap").update(CONST.Handicap_Names[this.handicap_index]);
        }
        else
        {
            this.your_color = CONST.Black_Color;
            this.opponent_color = CONST.White_Color;
            this.handicap_id = "your_handicap";
            this.komi_id = "opponent_handicap";
            $("your_color").update("black");
            $("your_color2").update("Black");
            $("your_handicap").update(CONST.Handicap_Names[this.handicap_index]);
            $("opponent_color").update("white");
            $("opponent_color2").update("White");
            $("opponent_handicap").update(CONST.Komi_Names[this.komi_index]);
        }            
    },
    
    rotate_board_sizes : function()
    {
        this.board_size_index += 1;
        if (this.board_size_index >= CONST.Board_Size_Names.length)
        {
            this.board_size_index = 0;
        }
        
        $("board_size").update(CONST.Board_Size_Names[this.board_size_index]);
        
        // make sure the handicap is valid; 9x9 and 13x13 only max 5 stone handicaps
        if (this.board_size_index != 0)
        {        
            if (CONST.Handicaps[this.handicap_index] > 5)
            {
                this.handicap_index = 5; // a little sloppy
                this.update_handicap();
            }            
        }
    },
    
    rotate_handicap : function()
    {
        this.handicap_index += 1;
        if (this.handicap_index >= CONST.Handicap_Names.length)
        {
            this.handicap_index = 0;
        }
        
        if (this.board_size_index != 0 && CONST.Handicaps[this.handicap_index] > 5)
        {
            this.handicap_index = 5;
        }
        
        this.update_handicap();
    },
    
    update_handicap : function()
    {
        $(this.handicap_id).update(CONST.Handicap_Names[this.handicap_index]);

        if (this.auto_komi)
            this.auto_update_komi();
    },

    rotate_komi : function()
    {
        this.auto_komi = false;
        this.komi_index += 1;
        if (this.komi_index >= CONST.Komi_Names.length)
        {
            this.komi_index = 0;
        }
        
        this.update_komi();
    },

    update_komi : function()
    {
        $(this.komi_id).update(CONST.Komi_Names[this.komi_index]);
    },

    auto_update_komi : function()
    {
        if (this.handicap_index == 0)
            komi_index = 0;
        else
            komi_index = CONST.Komi_None;

        if (this.komi_index != komi_index) {
            this.komi_index = komi_index;
            this.update_komi();
        }
    },

    rotate_your_handicap : function()
    {
        if (this.your_color == CONST.Black_Color)
            this.rotate_handicap();
        else
            this.rotate_komi();
    },
    
    rotate_opponent_handicap : function()
    {
        if (this.opponent_color == CONST.Black_Color)
            this.rotate_handicap();
        else
            this.rotate_komi();
    },
    
    create_game : function()
    {        
        if (this.valid)
        {
            var self = this;
            var params = {
                "your_name": $("your_name").value,
                "your_contact": $("your_contact").value,
                "opponent_name": $("opponent_name").value,
                "opponent_contact": $("opponent_contact").value,
                "your_color": this.your_color,
                "board_size_index": this.board_size_index,
                "handicap_index": this.handicap_index,
                "komi_index": this.komi_index,
                "your_contact_type": this.your_contact_type,
                "opponent_contact_type": this.opponent_contact_type
            };

            if (this.showing_twitter_password)
            {
                var tp = $("twitter_password").value;
                if (tp && tp.length > 1)
                {
                    params["your_twitter_password"] = tp;
                }                
            }
                                
            new Ajax.Request(
                "/service/create-game/",
                {
                    method: 'POST',                

                    parameters : params,
                
                    onSuccess: function(transport) 
                    {
                        var response = eval_json(transport.responseText);
                        if (response['success'])
                        {
                            if (response['need_your_twitter_password'])
                            {
                                self._require_twitter_password(response['flash']);
                            }                            
                            else
                            {
                                self._succeed_create_game(response['your_cookie'], response['your_turn']);
                            }
                        }
                        else
                        {                    
                            self._fail_create_game(response['flash']);
                        }
                    },
                
                    onFailure: function() 
                    {
                        self._fail_create_game("Sorry, but an unknown failure occured. Please try again."); 
                    }
                }
            );
        }
    },

    _succeed_create_game : function(your_cookie, your_turn)
    {
        this._hide_twitter_password();
        $("play_link").href = "/play/" + your_cookie + "/";
        
        if (your_turn)
        {
            $("play_link").update("Play the game &raquo;");
            $("flash").update("Your game is ready and it&#146;s your turn!");
        }
        else
        {
            $("play_link").update("View the game &raquo;");
            $("flash").update("Your game is ready; it&#146;s your opponent&#146;s turn.");
        }
        
        Effect.Appear("flash");
    },

    _show_twitter_password : function()
    {
        if (this.showing_twitter_password) { return; }
        $("twitter_password_container").removeClassName("hide");
        this.showing_twitter_password = true;
    },

    _hide_twitter_password : function()
    {
        if (!this.showing_twitter_password) { return; }
        $("twitter_password_container").addClassName("hide");
        $("flash").update("");
        this.showing_twitter_password = false;
    },
    
    _require_twitter_password : function(flash)
    {
        this._show_twitter_password();
        $("flash").update(flash);
        Effect.Appear("flash");
    },
    
    _fail_create_game : function(flash)
    {
        this._hide_twitter_password();
        $("flash").update(flash);        
        Effect.Appear("flash");
    },

    _activate_play_link : function()
    {
        $("play_link").removeClassName("disabled");
    },
    
    _deactivate_play_link : function()
    {
        $("play_link").addClassName("disabled");
    },
    
    _evaluate_validity : function()
    {
        var newValid = this.valid_your_name && this.valid_your_contact && this.valid_opponent_name && this.valid_opponent_contact;
        
        if (newValid != this.valid)
        {
            this.valid = newValid;
            if (newValid)
            {
                this._activate_play_link();
            }
            else
            {
                this._deactivate_play_link();
            }
        }        
    },
    
    _initialize_events : function()
    {
        $("your_name").observe('keyup', this._input_your_name.bindAsEventListener(this));
        $("your_contact").observe('keyup', this._input_your_contact.bindAsEventListener(this));
        $("opponent_name").observe('keyup', this._input_opponent_name.bindAsEventListener(this));
        $("opponent_contact").observe('keyup', this._input_opponent_contact.bindAsEventListener(this));        
    },
    
    _input_your_name : function()
    {
        this.valid_your_name = $("your_name").value.length > 0;
        this._evaluate_validity();
    },
    
    _input_your_contact : function()
    {
        this.valid_your_contact = ContactValidator.is_probably_good_contact($("your_contact").value, this.your_contact_type);
        this._evaluate_validity();
    },
    
    _input_opponent_name : function()
    {
        this.valid_opponent_name = $("opponent_name").value.length > 0;
        this._evaluate_validity();
    },
    
    _input_opponent_contact : function()
    {
        this.valid_opponent_contact = ContactValidator.is_probably_good_contact($("opponent_contact").value, this.opponent_contact_type);
        this._evaluate_validity();
    }
});



//-----------------------------------------------------------------------------
// Game Board (Model)
//-----------------------------------------------------------------------------

var GameBoard = Class.create({
    initialize : function(board_size_index)
    {
        // basic board setup
        this.size_index = board_size_index;        
        this.width = CONST.Board_Sizes[this.size_index][0];
        this.height = CONST.Board_Sizes[this.size_index][1];

        // empty out the board's contents
        this.board = null;
        this.owner = null;
        this.speculation = null;        
        this._make_blank_board(); 
    },

    get_width : function()
    {
        return this.width;
    },

    get_height : function()
    {
        return this.height;
    },

    set_point : function(x, y, color, owner, speculation)
    {
        this.board[x][y] = color;
        this.owner[x][y] = owner;
        this.speculation[x][y] = speculation;
    },

    clear_point : function(x, y)
    {
        this.board[x][y] = CONST.No_Color;
        this.owner[x][y] = CONST.No_Color;
        this.speculation[x][y] = false;
    },

    get_point : function(x, y)
    {
        return this.board[x][y];
    },

    get_owner : function(x, y)
    {
        return this.owner[x][y];
    },

    is_speculation : function(x, y)
    {
        return this.speculation[x][y];
    },

    set_from_state_string : function(state_string)
    {
        var i = 0;
        
        for (var y = 0; y < this.height; y++)
        {
            for (var x = 0; x < this.width; x++)
            {
                this.speculation[x][y] = false;

                // State string legend:
                //  . = no stone
                //  B = no stone; black territory
                //  W = no stone; white territory
                //  b = black stone
                //  c = black stone (dead)
                //  w = white stone
                //  x = white stone (dead)

                // I NEVER knew this, but charAt() is the only x-browser-safe
                // way to access individual characters in a string. Array
                // notation works okay in chrome, firefox, and safari but
                // not at all in IE. Woah.
                switch (state_string.charAt(i))
                {
                case 'b':
                case 'c':
                    this.board[x][y] = CONST.Black_Color;
                    break;

                case 'w':
                case 'x':
                    this.board[x][y] = CONST.White_Color;
                    break;

                default:
                    this.board[x][y] = CONST.No_Color;
                    break;
                }

                switch (state_string.charAt(i))
                {
                case 'B':
                case 'x':
                    this.owner[x][y] = CONST.Black_Color;
                    break;

                case 'W':
                case 'c':
                    this.owner[x][y] = CONST.White_Color;
                    break;

                default:
                    this.owner[x][y] = CONST.No_Color;
                    break;
                }

                i += 1;
            }
        }
    },

    clone : function(x, y)
    {
        var cloned = new GameBoard(this.size_index);
        for (var x = 0; x < this.width; x++)
        {
            for (var y = 0; y < this.height; y++)
            {
                cloned.set_point(x, y, this.board[x][y], this.owner[x][y], this.speculation[x][y]);
            }
        }

        return cloned;
    },
        
    _make_blank_board : function()
    {
        this.board = [];
        this.owner = [];
        this.speculation = [];
        
        for (var x = 0; x < this.width; x++)
        {
            var x_row = [];
            var o_row = [];
            var spec_row = [];
            
            for (var y = 0; y < this.height; y++)
            {
                x_row.push(CONST.No_Color);
                o_row.push(CONST.No_Color);
                spec_row.push(false);
            }

            this.board.push(x_row);
            this.owner.push(o_row);
            this.speculation.push(spec_row);
        }        
    }
    
});


//-----------------------------------------------------------------------------
// Game State (Model)
//-----------------------------------------------------------------------------

var GameState = Class.create({
    initialize : function(board, whose_move, white_stones_captured, black_stones_captured)
    {
        this.board = board;
        this.whose_move = whose_move;
        this.white_stones_captured = white_stones_captured;
        this.black_stones_captured = black_stones_captured;
    },

    get_white_stones_captured : function()
    {
        return this.white_stones_captured;
    },

    get_black_stones_captured : function()
    {
        return this.black_stones_captured;
    },

    are_stones_captured : function()
    {
        return (this.white_stones_captured > 0) || (this.black_stones_captured > 0);
    },

    get_whose_move : function()
    {
        return this.whose_move;
    },

    set_whose_move : function(whose_move)
    {
        this.whose_move = whose_move;
    },    

    set_white_stones_captured : function(amount)
    {
        this.white_stones_captured = amount;
    },

    set_black_stones_captured : function(amount)
    {
        this.black_stones_captured = amount;
    },
    
    increment_white_stones_captured : function(amount)
    {
        this.white_stones_captured += amount;        
    },

    increment_black_stones_captured : function(amount)
    {
        this.black_stones_captured += amount;
    },
    
    clone : function()
    {
        var cloned_board = this.board.clone();
        var cloned = new GameState(cloned_board, this.whose_move, this.white_stones_captured, this.black_stones_captured);
        return cloned;
    }
});


//-----------------------------------------------------------------------------
// Game Board View
//-----------------------------------------------------------------------------

var GameBoardView = Class.create({
    initialize : function(controller, board, click_callback, show_grid)
    {
        this.controller = controller;
        this.board = board;
        this.size_index = board.size_index;
        this.width = board.width;
        this.height = board.height;

        // blinking junxy junx -- you wouldn't need most of this
        // if you didn't also support cancel...
        this.is_blinking = false;
        this.blink_count = 0;
        this.blink_id = 0;
        this.blink_x = -1;
        this.blink_y = -1;

        // set up event management
        this.click_callback = click_callback;
        this.hover_callback = null;
        this.showing_grid = show_grid;
        
        // generate the visuals
        this._make_board_dom(show_grid);
        this._observe_point_clicks();
    },

    board_class : function()
    {
        return CONST.Board_Classes[this.size_index];
    },

    show_grid : function()
    {
        if (this.showing_grid) { return; }
        $('board_and_grid_container').select(".grid-top").each( function f(elt) { elt.removeClassName("hide"); } );
        $('board_and_grid_container').select(".grid-left").each( function f(elt) { elt.removeClassName("hide"); } );
        this.showing_grid = true;
    },

    hide_grid : function()
    {
        if (!this.showing_grid) { return; }
        $('board_and_grid_container').select(".grid-top").each( function f(elt) { elt.addClassName("hide"); } );
        $('board_and_grid_container').select(".grid-left").each( function f(elt) { elt.addClassName("hide"); } );
        this.showing_grid = false;
    },

    set_board : function(board)
    {
        // NOTE new board must have same size as old board
        this.board = board;
        this.update_dom();
    },
    
    update_dom : function()
    {
        for (var x = 0; x < this.width; x++)
        {
            for (var y = 0; y < this.height; y++)
            {
                this.update_dom_at(x, y);
            }
        }
    },

    update_dom_at : function(x, y)
    {
        var point = $(this._point_id(x, y));

        var new_class = this._point_class(x, y);
        if (new_class != point.className)
        {
            point.removeClassName(point.className);
            point.addClassName(new_class);
        }
        
        point.src = this._point_src(x, y);
    },

    observe_hovers : function(new_hover_callback)
    {
        if (this.hover_callback != null) { return; }

        this.hover_callback = new_hover_callback;
        
        for (var y = 0; y < this.height; y++)
        {
            for (var x = 0; x < this.width; x++)
            {
                var piece = $(this._point_id(x, y));
                piece.observe('mouseover', this._mouseover_point.bindAsEventListener(this, x, y));
            }
        }
    },

    stop_observing_hovers : function()
    {
        if (this.hover_callback == null) { return; }
        
        for (var y = 0; y < this.height; y++)
        {
            for (var x = 0; x < this.width; x++)
            {
                var piece = $(this._point_id(x, y));
                piece.stopObserving('mouseover');
            }
        }

        this.hover_callback = null;
    },

    _mouseover_point : function(e, x, y)
    {
        if (this.hover_callback != null)
        {
            this.hover_callback(x, y);
        }
    },
    
    highlight_at : function(x, y)
    {
        var point = $(this._point_id(x, y));
        point.src = "/img/highlight.png";
    },

    unhighlight_at : function(x, y)
    {
        var point = $(this._point_id(x, y));
        point.src = this._point_src(x, y);
    },

    blink_at : function(x, y)
    {
        if (this.is_blinking) { return; }
        if ((x < 0) || (x >= this.width) || (y < 0) || (y >= this.width)) { return; }
        
        this.is_blinking = true;
        this.blink_count = 0;
        this.blink_x = x;
        this.blink_y = y;
        this.blink_id = this._do_blink.bind(this).delay(0, x, y);
    },

    force_blink_at : function(x, y)
    {
        this.cancel_blink();
        this.blink_at(x, y);
    },

    cancel_blink : function()
    {
        if (this.is_blinking)
        {
            if (this.blink_id != 0)
            {
                window.clearTimeout(this.blink_id);
                this.blink_id = 0;
            }
            
            this.unhighlight_at(this.blink_x, this.blink_y);
            this.blink_x = -1;
            this.blink_y = -1;

            this.is_blinking = false;
        }
    },

    _do_blink : function(x, y)
    {
        if ((this.blink_count % 2) == 0)
        {
            this.highlight_at(x, y);
        }
        else
        {
            this.unhighlight_at(x, y);
        }
        
        this.blink_count += 1;
        
        if (this.blink_count < 6)
        {
            this.blink_id = this._do_blink.bind(this).delay(0.5, x, y);
        }
        else
        {
            this.is_blinking = false;
            this.blink_count = 0;
            this.blink_x = -1;
            this.blink_y = -1;
            this.blink_id = 0;
        }
    },
    
    _point_src : function(x, y)
    {
        if (this.board.is_speculation(x, y))
        {
            var b = this.board.get_point(x, y);
            if (b == CONST.Black_Color)
            {
                return "/img/ghost-black.png";
            }
            else if (b == CONST.White_Color)
            {
                return "/img/ghost-white.png";
            }          
        }
        else
        {
            var o = this.board.get_owner(x, y);
            if (o == CONST.Black_Color)
            {
                if (this.board.get_point(x, y) == CONST.White_Color)
                    return "/img/dead-white.png";
                else
                    return "/img/territory-black.png";
            }
            else if (o == CONST.White_Color)
            {
                if (this.board.get_point(x, y) == CONST.Black_Color)
                    return "/img/dead-black.png";
                else
                    return "/img/territory-white.png";
            }
        }

        return "/img/transparent-1x1.png";
    },
    
    _point_class : function(x, y)
    {
        if (!this.board.is_speculation(x, y))
        {
            var b = this.board.get_point(x, y);
            var o = this.board.get_owner(x, y);

            if (b == CONST.Black_Color && o != CONST.White_Color)
            {
                return "black";
            }
            else if (b == CONST.White_Color && o != CONST.Black_Color)
            {
                return "white";
            }
        }
        
        return this._default_point_class(x, y);
    },

    _is_star_point : function(x, y)
    {
        var x_is_ordinal = false;
        var y_is_ordinal = false;
        var ordinals = CONST.Star_Ordinals[this.size_index];

        // Don't really need a loop here since we know the length to begin with...
        for (var i = 0; i < ordinals.length; i++)
        {
            if (x == ordinals[i])
            {
                x_is_ordinal = true;
            }
            
            if (y == ordinals[i])
            {
                y_is_ordinal = true;
            }
        }
        
        return x_is_ordinal && y_is_ordinal;
    },

    _default_point_class : function(x, y)
    {
        if (x == 0)
        {
            if (y == 0)
            {
                return "tl";
            }
            else if (y == (this.height - 1))
            {
                return "bl";
            }
            else
            {
                return "left";
            }
        }
        else if (x == (this.width - 1))
        {
            if (y == 0)
            {
                return "tr";
            }
            else if (y == (this.height - 1))
            {
                return "br";
            }
            else
            {
                return "right";
            }
        }
        else if (y == 0)
        {
            return "top";
        }
        else if (y == (this.height - 1))
        {
            return "bottom";
        }
        else if (this._is_star_point(x, y) && this.board.get_owner(x, y) == CONST.No_Color)
        {
            return "star";
        }
        else
        {
            return "center";
        }
    },
    
    _point_id : function(x, y)
    {
        return 'piece_' + x.toString() + '_' + y.toString();
    },

    point_name : function(x, y)
    {
        return CONST.Column_Names[x] + '' + (this.controller.get_board_height()-y).toString();
    },                          

    _make_board_dom : function(show_grid)
    {
        var container = $("board_container");
        var html = "";
        
        for (var y = 0; y < this.height; y++)
        {
            html += '<div class="board_row">';
            for (var x = 0; x < this.width; x++)
            {
                html += '<img id="' + this._point_id(x, y) + '" src="' + this._point_src(x, y) + '" class="' + this._point_class(x, y) + '" />';
            }
            html += "</div>";
        }

        container.innerHTML = html;
    },

    _observe_point_clicks : function()
    {
        for (var y = 0; y < this.height; y++)
        {
            for (var x = 0; x < this.width; x++)
            {
                var piece = $(this._point_id(x, y));
                piece.observe('click', this._click_point.bindAsEventListener(this, x, y));
            }
        }        
    },

    _stop_observing_point_clicks : function()
    {
        for (var y = 0; y < this.height; y++)
        {
            for (var x = 0; x < this.width; x++)
            {
                var piece = $(this._point_id(x, y));
                piece.stopObserving('click');
            }
        }        
    },
    
    _click_point : function(e, x, y)
    {
        this.click_callback(e, x, y);
    }

});


//-----------------------------------------------------------------------------
// Chat Controller (rock and roll!)
//-----------------------------------------------------------------------------

var ChatController = Class.create({
    initialize : function(your_cookie, has_history)
    {
        this.your_cookie = your_cookie;
        this.has_history = has_history;
        this.is_listening_to_chat = false;
        this.next_listen_timeout = 10; /* in seconds */
        this.can_update = false;
        this.last_chat_seen = 0;

        this.remaining_state = CONST.Dim;
        this.remaining_visible = false;
        this.is_focused = false;
        new Effect.Opacity("characters_remaining", {to: 0.0, duration: 0.1});

        $("chat_textarea").observe('focus', this._focus_chat_textarea.bindAsEventListener(this));
        $("chat_textarea").observe('blur', this._blur_chat_textarea.bindAsEventListener(this));
        $("chat_textarea").observe('keyup', this._keyup_chat_textarea.bindAsEventListener(this));        
    },

    start_listening_to_chat : function()
    {
        if (this.is_listening_to_chat) { return; }
        this.is_listening_to_chat = true;        
        this.next_listen_timeout = 0; /* in seconds */
        this._check_for_chat.bind(this).delay(this.next_listen_timeout);
    },

    stop_listening_to_chat : function()
    {
        if (!this.is_listening_to_chat) { return; }
        this.is_listening_to_chat = false;
    },

    paste_text : function(extra_text)
    {
        var current_text = $("chat_textarea").value;
        if (!current_text) { current_text = ""; }

        if (current_text.length > 0)
        {
            // does it end with a space character? if so, directly append the extra text.
            // if not, append a space and _then_ the extra text.
            var ends_with_space = current_text.match(/\s$/);
            if (ends_with_space)
            {
                $("chat_textarea").value = current_text + extra_text;
            }
            else
            {
                $("chat_textarea").value = current_text + " " + extra_text;
            }
        }
        else
        {
            $("chat_textarea").value = extra_text;
        }

        this._update_characters_remaining();
        this._show_characters_remaining();
        set_cursor_position($("chat_textarea"), $("chat_textarea").value.length);
    },

    _check_for_chat : function()
    {
        var self = this;
        new Ajax.Request(
            "/service/recent-chat/",
            {
                method: 'POST',
                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "last_chat_seen": this.last_chat_seen
                },

                onSuccess : function(transport)
                {
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._append_chat_contents(response['chat_count'], response['recent_chats']);
                    }
                    self._keep_listening_to_chat();
                },

                onFailure : function()
                {
                    self._keep_listening_to_chat();
                }
            }
        );        
    },

    _keep_listening_to_chat : function()
    {
        if (!this.is_listening_to_chat) { return; }
        
        this.next_listen_timeout += 10;
        if (this.next_listen_timeout > 5 * 60)
        {
            this.next_listen_timeout = 5 * 60; /* 5 minutes max delay */
        }
        this._check_for_chat.bind(this).delay(this.next_listen_timeout);
    },

    _linkify_urls : function(string, extra_anchor_content)
    {
        if (!extra_anchor_content)
        {
            extra_anchor_content = "";
        }
        
        var url_regex = /((http\:\/\/|https\:\/\/|ftp\:\/\/)|(www\.))+(\w+:{0,1}\w*@)?(\S+)(:[0-9]+)?(\/|\/([\w#!:.?+=&%@!\-\/]))?/gi;

        var self = this;
        string = string.replace
        (
            url_regex,
            function(matched_text)
            {
                var test_text = matched_text.toLowerCase();
                var format_match = test_text.match(/^([a-z]+:\/\/)/);                
                var final_url;

                if (format_match)
                {
                    final_url = matched_text;
                }
                else
                {
                    final_url = 'http://' + matched_text;
                }
                
                return '<a href="' + final_url + '" ' + extra_anchor_content + '>' + matched_text + '</a>';
            }
        );

        return string;        
    },

    linkify_move_number : function(string)
    {
        if (string.length < 2)
            return string;
        if (string.charAt(0) != "#")
            return string;

        var move = string.substr(1);
        if (isNaN(parseInt(move)))
            return string;

        var href = "";
        if (this.has_history) {
            href = 'javascript:history_controller.set_move_number(' + move + ');';
        } else {
            href = '/history/' + this.your_cookie + '/' + move + '/';
        }
        return '<a href="' + href + '" class="subtle-link" >' + string + '</a>';
    },

    _linkify_move_numbers : function(string)
    {
        // Allow any positive integer starting from "0", but don't allow
        // numbers like "01".
        var move_regex = /\B#(0|[1-9]\d*)\b/g;
        
        var self = this;
        string = string.replace
        (
            move_regex,
            function(matched_text)
            {
                return self.linkify_move_number(matched_text);
            }
        );
        return string;
    },

    _linkify_board_coordinates : function(string)
    {
        var board_regex = /\b[A-T]\d{1,2}\b/gi;

        var self = this;
        string = string.replace
        (
            board_regex,
            function(matched_text)
            {
                var inner_regex = /[A-T]\d{1,2}/i;
                return matched_text.replace
                (
                    inner_regex,
                    function(inner_matched_text)                    
                    {
                        // compute x
                        var x_name = inner_matched_text.toUpperCase().charAt(0);

                        var x = -1;
                        for (var i = 0; i < 19; i++)
                        {
                            if (CONST.Column_Names[i] == x_name)
                            {
                                x = i + 1;
                                break;
                            }
                        }

                        // bounds check x
                        var controller = self.has_history ? history_controller : game_controller;
                        if (x < 1 || x > controller.get_board_width())
                        {
                            return inner_matched_text;
                        }

                        // compute y
                        var y_str = inner_matched_text.substr(1);                        
                        y = parseInt(y_str, 10);

                        // bounds check y
                        if (isNaN(y) || y < 1 || y > controller.get_board_height())
                        {
                            return inner_matched_text;
                        }

                        // linkify! (and account for the fact that we're 1-based when writing out grid squares as text.)
                        var controller_name = self.has_history ? "history_controller" : "game_controller";
                        return '<a href="javascript:' + controller_name + '.get_board_view().force_blink_at(' + (x-1).toString() + ',' + (controller.get_board_height()-y).toString() + ');" class="subtle-link" >' + inner_matched_text + '</a>';
                    }
                );
            }
        );

        return string;
    },

    _process_chat_message : function(message)
    {
        var processed_message = this._linkify_urls(message, 'class="subtle-link" target="_blank" rel="nofollow"');
        processed_message = this._linkify_board_coordinates(processed_message);
        processed_message = this._linkify_move_numbers(processed_message);
        return processed_message;
    },
    
    _append_chat_contents : function(chat_count, chats)
    {
        if (this.last_chat_seen == chat_count) { return; }
        
        var chat_html = $("chat_contents").innerHTML;

        if (!chat_html)
        {
            chat_html = "";
        }

        var self = this;
        
        chats.each(function(chat) {
            var name = chat['name'];
            var message = chat['message'];
            var move_number = chat['move_number'];
            var processed_message = self._process_chat_message(message);
            var move_link = self.linkify_move_number('#' + move_number);
            chat_html = '<div class="chat_entry"><span class="chat_move_number">' + move_link + '</span><span class="chat_separator"> </span><span class="chat_name">' + name + '</span><span class="chat_separator">: </span><span class="chat_message">' + processed_message + '</span></div>' + chat_html;
        });

        if (chat_html.length < 1)
        {
            chat_html = "&nbsp;";
        }

        $("chat_contents").update(chat_html);

        this.last_chat_seen = chat_count;
        this.next_listen_timeout = 0;
    },

    _focus_chat_textarea : function(e)
    {
        this._show_characters_remaining();
        this.is_focused = true;
    },

    _blur_chat_textarea : function(e)
    {
        this.is_focused = false;
        if (this._get_characters_remaining() == 140)
        {
            this._hide_characters_remaining();
        }
    },
    
    _keyup_chat_textarea : function(e)
    {
        if (!this.is_focused)
        {
            /* will only happen if user quickly clicks in text area while browser is loading */
            this._focus_chat_textarea(e);
        }
        
        var amount_o_text =  $("chat_textarea").value.length;
        if (amount_o_text < 1)
        {
            this._deactivate_chat_update_link();
            this._zero_text();
        }
        else
        {
            this._activate_chat_update_link();
        }

        this._update_characters_remaining();        
        
        if (e.keyCode == Event.KEY_RETURN)
        {
            this.update_chat();
        }
    },

    _zero_text : function()
    {
        $("chat_textarea").value = ""; /* zero out the text */
        this._update_characters_remaining();
        if (!this.is_focused)
        {
            this._hide_characters_remaining();
        }
    },

    _show_characters_remaining : function()
    {
        if (this.remaining_visible) { return; }

        this.remaining_visible = true;
        this._update_characters_remaining();
        new Effect.Opacity("characters_remaining", {to: 1.0, duration: 0.2});        
    },

    _hide_characters_remaining : function()
    {
        if (!this.remaining_visible) { return; }

        this.remaining_visible = false;
        new Effect.Opacity("characters_remaining", {to: 0.0, duration: 0.2});
    },

    _get_characters_remaining : function()
    {
        return (140 - $("chat_textarea").value.length);
    },
    
    _update_characters_remaining : function()
    {
        var characters_remaining = this._get_characters_remaining();

        $("characters_remaining").update(characters_remaining.toString());
        
        if (characters_remaining > 20)
        {
            if (this.remaining_state == CONST.Dim) { return; }

            this.remaining_state = CONST.Dim;
            $("characters_remaining").removeClassName("notable");
            $("characters_remaining").removeClassName("dangerous");
            $("characters_remaining").addClassName("dim");
        }
        else if (characters_remaining > 10)
        {
            if (this.remaining_state == CONST.Notable) { return; }

            this.remaining_state = CONST.Notable;
            $("characters_remaining").removeClassName("dim");
            $("characters_remaining").removeClassName("dangerous");
            $("characters_remaining").addClassName("notable");
        }
        else
        {
            if (this.remaining_state == CONST.Dangerous) { return; }

            this.remaining_state = CONST.Dangerous;
            $("characters_remaining").removeClassName("dim");
            $("characters_remaining").removeClassName("notable");
            $("characters_remaining").addClassName("dangerous");            
        }        
    },

    _activate_chat_update_link : function()
    {
        if (this.can_update) { return; }
        
        $("chat_update_link").removeClassName("disabled_move_link");
        $("chat_update_link").addClassName("move_link");
        
        this.can_update = true;        
    },

    _deactivate_chat_update_link : function()
    {
        if (!this.can_update) { return; }

        $("chat_update_link").removeClassName("move_link");
        $("chat_update_link").addClassName("disabled_move_link");
        $("chat_update_link").update("update &raquo;");
        
        this.can_update = false;
    },

    update_chat : function()
    {
        if (!this.can_update) { return; }
        var message = $("chat_textarea").value;
        if (message.length < 1) { return; }

        var self = this;
        new Ajax.Request(
            "/service/add-chat/",
            {
                method: 'POST',
                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "message": message,
                    "last_chat_seen": this.last_chat_seen
                },

                onSuccess : function(transport)
                {
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._hide_chat_error();

                        if (!(response['no_message']))
                        {
                            self._append_chat_contents(response['chat_count'], response['recent_chats']);
                        }

                        self._zero_text();
                        self.can_update = true;
                        self._deactivate_chat_update_link();                                                    
                    }
                    else
                    {
                        self._show_chat_error(response['flash']);
                    }
                },

                onFailure : function()
                {
                    self._show_chat_error('Sorry, but an unexpected error occured. Try chatting again in a few minutes.');
                }
            }
        );
    },

    _hide_chat_error : function()
    {
        $("chat_error").update("&nbsp;");
        $("chat_error").addClassName("hide");
    },

    _show_chat_error : function(message)
    {
        $("chat_error").update(message);
        $("chat_error").removeClassName("hide");
    }    
});


//-----------------------------------------------------------------------------
// Game Controller (for both state and board)
//-----------------------------------------------------------------------------

var GameController = Class.create({            
    initialize : function(your_cookie, your_color, current_move_number, whose_move, board_size_index, board_state_string, white_stones_captured, black_stones_captured, your_name, opponent_name, opponent_contact, opponent_contact_type, wants_email, last_move_x, last_move_y, last_move_was_pass, you_are_done_scoring, opponent_done_scoring, scoring_number, game_is_scoring, you_win, opponent_wins, game_is_finished, last_move_message, show_grid)
    {
        this.your_cookie = your_cookie;
        this.your_color = your_color;
        this.current_move_number = current_move_number;
        
        this.wants_email = wants_email;
        this.toggling_wants_email = false;

        this.showing_last_move = false;
        this.showing_last_move_count = 0;
        this.last_move_x = last_move_x;
        this.last_move_y = last_move_y;
        this.last_move_was_pass = last_move_was_pass;
        this.game_is_finished = game_is_finished;
        
        this.your_name = your_name;
        this.opponent_name = opponent_name;
        this.opponent_contact = opponent_contact;
        this.opponent_contact_type = opponent_contact_type;

        this.last_move_message = last_move_message;

        this.speculation = null;
        this.isSpeculating = false;
        this.inHistory = false;
        this.speculation_color = your_color;
        this.move_x = -1;
        this.move_y = -1;
        this.previous_owner = CONST.No_Color;

        this.game_is_scoring = game_is_scoring;
        this.you_are_done_scoring = you_are_done_scoring;
        this.opponent_done_scoring = opponent_done_scoring;
        this.scoring_number = scoring_number;
        this.you_win = false;
        this.opponent_wins = false;

        this.is_loading = false;
        this.is_waiting_for_opponent = false;
        this.next_update_timeout = 10; /* in seconds */

        var self = this;

        this.board = new GameBoard(board_size_index);
        this.board.set_from_state_string(board_state_string);
        this.board_view = new GameBoardView(this, this.board, function(e, x, y) { self._click_board(e, x, y); }, show_grid);

        this.state = new GameState(this.board, whose_move, white_stones_captured, black_stones_captured);

        // hack to make IE happy (since the POS ignores initial inline opacity values)
        this.is_loading = true;
        this._stop_loading();

        this.is_grid_active = show_grid;
        $("grid_button").observe('click', this._click_grid_button.bindAsEventListener(this));        
        
        if ((!this.is_your_move() || this.game_is_scoring) && !this.game_is_finished) 
        {
            this.start_waiting_for_opponent();
        }
    },


    //--------------------------------------------------------------------------
    // grid square naming/button management
    //--------------------------------------------------------------------------

    _click_grid_button : function(e)
    {
        if (this.is_grid_active)
        {
            this.deactivate_grid();
        }
        else
        {
            this.activate_grid();
        }
    },

    _selected_square : function(x, y)
    {
        var name = game_controller.get_board_view().point_name(x, y);        
        this.board_view.force_blink_at(x, y);
        chat_controller.paste_text(name + " ");
    },

    activate_grid : function()
    {
        if (this.is_grid_active) { return; }
        this.is_grid_active = true;
        $("grid_button").removeClassName("grid_disabled");
        $("grid_button").addClassName("grid_enabled");
        game_controller.get_board_view().show_grid();
        
        var board_class = game_controller.get_board_view().board_class();
        var right_board_class = "right_" + board_class;
        var with_grid = right_board_class + "_grid";
        $("game_info").removeClassName(right_board_class);
        $("game_info").addClassName(with_grid);

        $("board_extras").addClassName("extras_grid");

        this._save_grid_preferences();
    },

    deactivate_grid : function()
    {
        if (!this.is_grid_active) { return; }
        this.is_grid_active = false;
        $("grid_button").removeClassName("grid_enabled");
        $("grid_button").addClassName("grid_disabled");
        game_controller.get_board_view().hide_grid();

        var board_class = game_controller.get_board_view().board_class();
        var right_board_class = "right_" + board_class;
        var with_grid = right_board_class + "_grid";
        $("game_info").removeClassName(with_grid);
        $("game_info").addClassName(right_board_class);

        $("board_extras").removeClassName("extras_grid");        
        
        this._save_grid_preferences();
    },

    _save_grid_preferences : function()
    {
        var self = this;
        this._start_loading();

        new Ajax.Request(
            "/service/change-grid-options/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "show_grid": (this.is_grid_active ? "true" : "false")
                },

                onSuccess : function(transport)
                {
                    // doesn't really matter whether we succeed...
                    self._stop_loading();
                },

                onFailure : function()
                {
                    // ...or fail. it's just a preference.
                    self._stop_loading();
                }
            }
        );
    },
    
    
    //--------------------------------------------------------------------------
    // accessor methods to get at information about the board
    //--------------------------------------------------------------------------

    get_point_name : function(x, y)
    {
        return this.board_view.point_name(x, y);
    },
    
    get_board_width : function()
    {
        return this.board.get_width();
    },

    get_board_height : function()
    {
        return this.board.get_height();
    },

    get_board_view : function()
    {
        return this.board_view;
    },
    
    
    //--------------------------------------------------------------------------
    // show last move
    //--------------------------------------------------------------------------
    
    show_last_move : function()
    {
        this.board_view.blink_at(this.last_move_x, this.last_move_y);
    },


    //--------------------------------------------------------------------------
    // switching moves
    //--------------------------------------------------------------------------        

    is_your_move : function()
    {
        return (!this.game_is_scoring) && (!this.game_is_finished) && (this.state.get_whose_move() == this.your_color);
    },

    start_scoring : function(white_territory, black_territory, scoring_number)
    {
        this.update_scoring(scoring_number, white_territory, black_territory);

        this.deactivate_pass_and_resign_links();
        this.activate_show_previous_link();
        this.show_captures_if_needed();

        $("playing_links").addClassName("hide");
        $("scoring_links").removeClassName("hide");
        $("territory_message").removeClassName("hide");

        // Always wait for opponent when scoring.
        this._set_scoring_message();
        this.start_waiting_for_opponent();
    },

    update_scoring : function(scoring_number, white_territory, black_territory)
    {
        this.scoring_number = scoring_number;
        this.update_territory(white_territory, black_territory);
    },

    update_territory : function(white_territory, black_territory)
    {
        this.white_territory = white_territory;
        this.black_territory = black_territory;
        $("white_territory").update(white_territory.toString());
        $("black_territory").update(black_territory.toString());
    },

    become_your_move : function(black_stones_captured, white_stones_captured)
    {
        this.move_x = -1;
        this.move_y = -1;
        
        this._set_move_message_for_no_piece();

        this.state = this.state.clone();
        this.state.set_whose_move(opposite_color(this.state.get_whose_move()));
        this.state.set_black_stones_captured(black_stones_captured);
        this.state.set_white_stones_captured(white_stones_captured);

        this.activate_view_history_link();
        this.activate_show_previous_link();
        this.activate_pass_and_resign_links();
        this.show_captures_if_needed();
    },

    become_opponents_move : function(black_stones_captured, white_stones_captured)
    {
        $("turn_message").update("You&#146;re waiting for " + this.opponent_name + " to move.");

        this.state = this.state.clone();
        this.state.set_whose_move(opposite_color(this.state.get_whose_move()));
        this.start_waiting_for_opponent();
        this.state.set_black_stones_captured(black_stones_captured);
        this.state.set_white_stones_captured(white_stones_captured);
        
        this.move_x = -1;
        this.move_y = -1;

        this.activate_view_history_link();
        this.activate_show_previous_link();
        this.deactivate_make_this_move_link();
        this.deactivate_pass_and_resign_links();
        this.show_captures_if_needed();
    },
    

    //--------------------------------------------------------------------------
    // link activation/deactivation
    //--------------------------------------------------------------------------            

    activate_view_history_link : function()
    {
        $("view_history").removeClassName("disabled_extra_link");
        $("view_history").addClassName("extra_link");
    },

    activate_show_previous_link : function()
    {
        $("show_previous_move").removeClassName("disabled_move_link");
        $("show_previous_move").addClassName("move_link");        
    },

    activate_pass_and_resign_links : function()
    {
        $("pass").removeClassName("disabled_move_link");
        $("pass").addClassName("move_link");
        var resign = $("resign");
        if (resign)
        {
            resign.removeClassName("disabled_move_link");
            resign.addClassName("move_link");
            $("pass_or_resign").removeClassName("disabled_text");
            $("pass_or_resign").addClassName("enabled_text");
        }
    },

    deactivate_pass_and_resign_links : function()
    {
        $("pass").removeClassName("move_link");
        $("pass").addClassName("disabled_move_link");
        var resign = $("resign");
        if (resign)
        {
            resign.removeClassName("move_link");
            resign.addClassName("disabled_move_link");
            $("pass_or_resign").removeClassName("enabled_text");
            $("pass_or_resign").addClassName("disabled_text");
        }
    },

    update_pass_links_after_last_was_not_pass : function()
    {
        if (this.is_your_move())
        {
            var link_class = "move_link";
            var text_class = "enabled_text";            
        }
        else
        {
            var link_class = "disabled_move_link";
            var text_class = "disabled_text";            
        }
        var new_html = '<a href="javascript:game_controller.pass_move();" id="pass" class="' + link_class + '">pass &raquo;</a> <span id="pass_or_resign" class="' + text_class + '">or</span> <a href="javascript:game_controller.resign_move();" id="resign" class="' + link_class + '">resign &raquo;</a>';
        $("pass_links_container").update(new_html);
    },

    update_pass_links_after_last_was_pass : function()
    {
        if (this.is_your_move())
        {
            var link_class = "move_link";
        }
        else
        {
            var link_class = "disabled_move_link";
        }
        var new_html = '<a href="javascript:game_controller.pass_move();" id="pass" class="' + link_class + '">declare game finished (pass) &raquo;</a>';
        $("pass_links_container").update(new_html);        
    },

    activate_make_this_move_link : function()
    {
        $("make_this_move").removeClassName("disabled_move_link");
        $("make_this_move").addClassName("move_link");
    },

    deactivate_make_this_move_link : function()
    {
        $("make_this_move").removeClassName("move_link");
        $("make_this_move").addClassName("disabled_move_link");
    },

    activate_done_scoring_link : function()
    {
        $("done_scoring").removeClassName("disabled_move_link");
        $("done_scoring").addClassName("move_link");
    },

    deactivate_done_scoring_link : function()
    {
        $("done_scoring").removeClassName("move_link");
        $("done_scoring").addClassName("disabled_move_link");
    },

    show_captures_if_needed : function()
    {
        if (this.state.are_stones_captured())
        {
            $("capture_message").removeClassName("hide");
        }
    },

    
    //--------------------------------------------------------------------------
    // waiting AJAX code
    //--------------------------------------------------------------------------            

    start_waiting_for_opponent : function()
    {
        if (this.is_waiting_for_opponent) { return; }
        this.next_update_timeout = 15; /* in seconds */
        this.wait_for_opponent();
        this.is_waiting_for_opponent = true;
    },

    wait_for_opponent : function()
    {
        if (this.game_is_finished) {
            this.stop_waiting_for_opponent();
        } else if (this.game_is_scoring) {
            this._has_opponent_scored.bind(this).delay(this.next_update_timeout);
        } else {
            this._has_opponent_moved.bind(this).delay(this.next_update_timeout);
        }

    },

    _has_opponent_moved : function()
    {
        if (this.game_is_scoring || this.game_is_finished) {
            return;
        }

        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/has-opponent-moved/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie
                },

                onSuccess : function(transport)
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        if (!response['has_opponent_moved'])
                        {
                            self._keep_waiting_for_opponent();
                        }
                        else
                        {
                            self._opponent_has_moved(response['board_state_string'], response['current_move_number'], response['black_stones_captured'], response['white_stones_captured'], response['last_move_message'], response['last_move_x'], response['last_move_y'], response['last_move_was_pass'], response['white_territory'], response['black_territory'], response['scoring_number'], response['game_is_scoring'], response['you_win'], response['opponent_wins'], response['game_is_finished']);
                        }
                    }
                    else
                    {
                        // something went wrong, so just keep waiting
                        self._keep_waiting_for_opponent();
                    }
                },

                onFailure : function()
                {
                    self._stop_loading();
                    // something went (very) wrong, so just keep waiting
                    self._keep_waiting_for_opponent();
                }
            }
        );
    },

    _opponent_has_moved : function(board_state_string, current_move_number, black_stones_captured, white_stones_captured, last_move_message, last_move_x, last_move_y, last_move_was_pass, white_territory, black_territory, scoring_number, game_is_scoring, you_win, opponent_wins, game_is_finished)
    {
        if (this.game_is_finished) {
            // There seem to be some corner cases where this message is
            // received late.
            return;
        }

        this.current_move_number = current_move_number;
        this.update_board(board_state_string);

        $("black_stones_captured").update(black_stones_captured.toString());
        $("white_stones_captured").update(white_stones_captured.toString());
        this.last_move_message = last_move_message;
        $("turn_message").update(last_move_message);

        this.last_move_x = last_move_x;
        this.last_move_y = last_move_y;
        this.last_move_was_pass = last_move_was_pass;
        this.game_is_scoring = game_is_scoring;
        this.game_is_finished = game_is_finished;
        this.you_win = you_win;
        this.opponent_wins = opponent_wins;

        if (this.last_move_was_pass)
        {
            this.update_pass_links_after_last_was_pass();
        }
        else
        {
            this.update_pass_links_after_last_was_not_pass();
        }
        
        this.stop_waiting_for_opponent();

        if (this.game_is_finished) {
            // In case an old window hasn't updated until now.
            this.update_scoring(scoring_number, white_territory, black_territory);

            if (!this.by_resignation())
            {
                $("territory_message").removeClassName("hide");
            }

            this.finish_game();
        } else if (this.game_is_scoring) {
            this.start_scoring(white_territory, black_territory, scoring_number);
        } else {
            this.become_your_move(black_stones_captured, white_stones_captured);
        }
    },

    update_board : function(board_state_string)
    {
        this.board.set_from_state_string(board_state_string);
        this.board_view.update_dom();
    },

    _keep_waiting_for_opponent : function()
    {
        this.next_update_timeout += 10; /* seconds */
        if (this.next_update_timeout > 5 * 60)
        {
            this.next_update_timeout = 5 * 60; /* 5 minutes max delay */
        }
        this.wait_for_opponent();
    },
    
    stop_waiting_for_opponent : function()
    {
        if (!this.is_waiting_for_opponent) { return ; }
        this.is_waiting_for_opponent = false;
    },

    _has_opponent_scored : function()
    {
        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/has-opponent-scored/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "scoring_number": this.scoring_number
                },

                onSuccess : function(transport)
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success']) {
                        if (!response['has_opponent_scored']) {
                            self._keep_waiting_for_opponent();
                        } else {
                            self._opponent_has_scored(response['you_are_done_scoring'],
                                                      response['opponent_done_scoring'],
                                                      response['scoring_number'],
                                                      response['board_state_string'],
                                                      response['white_territory'],
                                                      response['black_territory'],
                                                      response['game_is_finished'],
                                                      response['you_win'],
                                                      response['opponent_wins']);
                        }
                    } else {
                        // something went wrong, so just keep waiting
                        self._keep_waiting_for_opponent();
                    }
                },

                onFailure : function()
                {
                    self._stop_loading();
                    // something went (very) wrong, so just keep waiting
                    self._keep_waiting_for_opponent();
                }
            }
        );
    },

    _opponent_has_scored : function(you_are_done_scoring, opponent_done_scoring, scoring_number, board_state_string, white_territory, black_territory, game_is_finished, you_win, opponent_wins)
    {
        this.stop_waiting_for_opponent();

        this.you_are_done_scoring = you_are_done_scoring;
        this.opponent_done_scoring = opponent_done_scoring;
        this.you_win = you_win;
        this.opponent_wins = opponent_wins;
        this.game_is_finished = game_is_finished;

        this.update_board(board_state_string);
        this.update_scoring(scoring_number, white_territory, black_territory);

        if (game_is_finished) {
            this.finish_game();
        } else if (you_are_done_scoring) {
            this.deactivate_done_scoring_link();
            this._set_you_are_done_message();
        } else {
            this.activate_done_scoring_link();

            if (opponent_done_scoring) {
                this._set_opponent_done_message();
            } else {
                this._set_scoring_message();
                this.start_waiting_for_opponent();
            }
        }
    },


    //--------------------------------------------------------------------------
    // move making
    //--------------------------------------------------------------------------    

    _set_move_message_for_no_piece : function()
    {
        $("turn_message").update(this.last_move_message);
        this.deactivate_make_this_move_link();
    },

    _set_move_message_for_one_piece : function()
    {
        $("turn_message").update("You can click elsewhere to choose a different move.");
        this.activate_make_this_move_link();
    },
    
    _set_scoring_message : function()
    {
        $("turn_message").update("Click on groups of stones to mark them as dead or alive.");
    },
    
    _set_you_are_done_message : function()
    {
        $("turn_message").update("You&#146;re waiting for " + this.opponent_name + " to finish scoring.");
    },
    
    _set_opponent_done_message : function()
    {
        $("turn_message").update(this.opponent_name + " has finished scoring.");
    },
    
    make_this_move : function()
    {
        if (!this.is_your_move())
        {
            return;
        }
        
        if (this.move_x == -1 || this.move_y == -1)
        {
            return;
        }

        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/make-this-move/",
            {
                method: 'POST',                

                parameters: 
                {
                    "your_cookie": this.your_cookie,
                    "current_move_number": this.current_move_number,
                    "move_x": this.move_x,
                    "move_y": this.move_y
                },

                onSuccess: function(transport) 
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._succeed_make_this_move(response['board_state_string'], response['white_stones_captured'], response['black_stones_captured'], response['current_move_number'], response['flash']);
                    }
                    else
                    {                    
                        self._fail_make_this_move(response['flash']);
                    }
                },

                onFailure: function() 
                {
                    self._stop_loading();
                    self._fail_make_this_move("Unexpected network error. Please try again.");
                }
            }
        );        
    },

    _succeed_make_this_move : function(board_state_string, white_stones_captured, black_stones_captured, current_move_number, flash)
    {
        this.current_move_number = current_move_number;
        this.last_move_x = this.move_x;
        this.last_move_y = this.move_y;
        this.board.set_from_state_string(board_state_string);
        this.board_view.update_dom();
        $("white_stones_captured").update(white_stones_captured.toString());
        $("black_stones_captured").update(black_stones_captured.toString());
        this.update_pass_links_after_last_was_not_pass();
        this.become_opponents_move(black_stones_captured, white_stones_captured);
    },

    _fail_make_this_move : function(flash)
    {
        $("turn_message").update(flash);        
    },

    pass_move : function()
    {
        if (!this.is_your_move())
        {
            return;
        }
        
        var confirmed = false;
        
        if (this.last_move_was_pass)
        {
            confirmed = confirm("Are you sure you want to pass? Because your opponent also passed, this will end the game.");
        }
        else
        {
            confirmed = confirm("Are you sure you want to pass? Your opponent will be allowed to move, or to decide to end the game.");
        }

        if (confirmed)
        {
            this._do_pass_move();
        }
    },

    _do_pass_move : function()
    {
        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/pass/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "current_move_number": this.current_move_number
                },

                onSuccess : function(transport)
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._succeed_pass(response['current_move_number'],
                                           response['white_territory'],
                                           response['black_territory'],
                                           response['scoring_number'],
                                           response['board_state_string'],
                                           response['game_is_scoring']);
                    }
                    else
                    {
                        self._fail_make_this_move(response['flash']);
                    }
                },

                onFailure: function()
                {
                    self._stop_loading();
                    self._fail_make_this_move("Unexpected network error. Please try again.");
                }
            }
        );
    },

    _succeed_pass : function(current_move_number, white_territory, black_territory, scoring_number, board_state_string, game_is_scoring)
    {
        this.current_move_number = current_move_number;
        this.game_is_scoring = game_is_scoring;
        if (this.game_is_scoring) {
            this.update_board(board_state_string);
            this.start_scoring(white_territory, black_territory, scoring_number);
        } else {
            this.become_opponents_move(this.state.get_black_stones_captured(), this.state.get_white_stones_captured());
            this.update_pass_links_after_last_was_pass();
        }
    },

    resign_move : function()
    {
        if (!this.is_your_move())
        {
            return;
        }
        
        if (confirm("Are you sure you want to resign? The game will immediately end."))
        {
            this._do_resign_move();
        }
    },

    _do_resign_move : function()
    {
        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/resign/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "current_move_number": this.current_move_number
                },

                onSuccess : function(transport)
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._resign_success(response['current_move_number']);
                    }
                    else
                    {
                        self._fail_make_this_move(response['flash']);
                    }
                },

                onFailure: function()
                {
                    self._stop_loading();
                    self._fail_make_this_move("Unexpected network error. Please try again.");
                }
            }
        );
    },
    
    _resign_success : function(current_move_number)
    {
        this.current_move_number = current_move_number;
        this.you_win = false;
        this.opponent_wins = true;

        this.finish_game();
    },

    by_resignation : function()
    {
        return this.game_is_finished
            && (this.you_win || this.opponent_wins)
            && this.scoring_number < 0;
    },

    finish_game : function()
    {
        this.game_is_scoring = false;

        var gameOver = "The game is over";
        if (this.you_win) {
            gameOver += ", and you won";
        } else if (this.opponent_wins) {
            gameOver += ", and " + this.opponent_name + " won";
        }
        
        if (this.by_resignation()) {
            gameOver += " by resignation";
        }

        if (this.opponent_contact_type == CONST.Email_Contact) {
            $("turn_message").update(gameOver + "! <a href=\"mailto:" + this.opponent_contact + "\" class=\"subtle-link\">Email your opponent</a> to discuss the game!");
        } else {
            $("turn_message").update(gameOver + "! <a href=\"http://twitter.com/home?status=@" + this.opponent_contact + " How was the game?\" class=\"subtle-link\">Twitter your opponent</a> to discuss the game!");
        }

        $("playing_links").addClassName("hide");
        $("scoring_links").addClassName("hide");
    },
    
    mark_stone : function(owner)
    {
        if (!this.game_is_scoring) {
            return;
        }

        if (this.you_are_done_scoring) {
            return
        }
        
        if (this.move_x == -1 || this.move_y == -1)
        {
            return;
        }

        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/mark-stone/",
            {
                method: 'POST',                

                parameters: 
                {
                    "your_cookie": this.your_cookie,
                    "stone_x": this.move_x,
                    "stone_y": this.move_y,
                    "owner": owner
                },

                onSuccess: function(transport) 
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._succeed_mark_stone(response['board_state_string'],
                                                 response['white_territory'],
                                                 response['black_territory'],
                                                 response['scoring_number'],
                                                 response['flash']);
                    }
                    else
                    {                    
                        self._fail_mark_stone(response['flash']);
                    }
                },

                onFailure: function() 
                {
                    self._stop_loading();
                    self._fail_mark_stone("Unexpected network error. Please try again.");
                }
            }
        );        
    },

    _succeed_mark_stone : function(board_state_string, white_territory, black_territory, scoring_number, flash)
    {
        this.move_x = -1;
        this.move_y = -1;

        this.update_board(board_state_string);
        this.update_scoring(scoring_number, white_territory, black_territory);
        this._set_scoring_message();

        if (this.opponent_done_scoring) {
            this.opponent_done_scoring = false;
            this.start_waiting_for_opponent();
        }
    },

    _fail_mark_stone : function(flash)
    {
        var x = this.move_x;
        var y = this.move_y;
        this.board.set_point(x, y, this.board.get_point(x, y), this.previous_owner, false);
        this.board_view.update_dom_at(x, y);

        this.move_x = -1;
        this.move_y = -1;
        this.previous_owner = CONST.No_Color;

        $("turn_message").update(flash);        
    },

    done_scoring : function()
    {
        if (this.you_are_done_scoring) {
            return;
        }

        if (!this.game_is_scoring) {
            return;
        }

        if (this.confirming_done) {
            return;
        }
        
        this.confirming_done = true;
        var confirmed = false;
        
        if (this.opponent_done_scoring)
        {
            confirmed = confirm("Are you sure you are finished scoring? Because your opponent is finished, this will finalize the score.");
        }
        else
        {
            confirmed = confirm("Are you sure you are finished scoring? Your opponent will be allowed restart scoring, or to finalize the score.");
        }

        if (confirmed)
        {
            this._do_done_scoring(this.scoring_number);
        }

        this.confirming_done = false;
    },

    _do_done_scoring : function(scoring_number)
    {
        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/done/",
            {
                method: 'POST',                

                parameters: 
                {
                    "your_cookie": this.your_cookie,
                    "scoring_number": scoring_number
                },

                onSuccess: function(transport) 
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._succeed_done_scoring(response['you_are_done_scoring'],
                                                   response['opponent_done_scoring'],
                                                   response['scoring_number'],
                                                   response['board_state_string'],
                                                   response['white_territory'],
                                                   response['black_territory'],
                                                   response['game_is_finished'],
                                                   response['you_win'],
                                                   response['opponent_wins'],
                                                   response['flash']);
                    }
                    else
                    {                    
                        self._fail_done_scoring(response['flash']);
                    }
                },

                onFailure: function() 
                {
                    self._stop_loading();
                    self._fail_done_scoring("Unexpected network error. Please try again.");
                }
            }
        );        
    },

    _succeed_done_scoring : function(you_are_done_scoring, opponent_done_scoring, scoring_number, board_state_string, white_territory, black_territory, game_is_finished, you_win, opponent_wins, flash)
    {
        this.you_are_done_scoring = you_are_done_scoring;
        this.opponent_done_scoring = opponent_done_scoring;
        this.you_win = you_win;
        this.opponent_wins = opponent_wins;
        this.game_is_finished = game_is_finished;

        this.update_board(board_state_string);
        this.update_scoring(scoring_number, white_territory, black_territory);

        if (!you_are_done_scoring) {
            $("turn_message").update(flash);
            return;
        }

        this.deactivate_done_scoring_link();

        if (game_is_finished) {
            this.finish_game();
        } else {
            this._set_you_are_done_message();
        }
    },

    _fail_done_scoring : function(flash)
    {
        $("turn_message").update(flash);
    },


    //--------------------------------------------------------------------------
    // ajax notification
    //--------------------------------------------------------------------------    
    
    _start_loading : function()
    {
        if (this.is_loading) { return; }

        this.is_loading = true;
        new Effect.Opacity("loading", {to: 1.0, duration: 0.2});
    },

    _stop_loading : function()
    {
        if (!this.is_loading) { return; }
        
        this.is_loading = false;
        new Effect.Opacity("loading", {to: 0.0, duration: 0.2});                        
    },

    
    //--------------------------------------------------------------------------
    // board click callbacks
    //--------------------------------------------------------------------------    

    _click_board : function(e, x, y)
    {
        if (this.inHistory)
        {
            // clicking has no effect when you're looking through history
            return;
        }
        else if (e.shiftKey && e.shiftKey == 1)
        {
            this._selected_square(x, y);
        }
        else if (this.isSpeculating)
        {
            this._click_board_speculate(x, y);
        }
        else if (this.is_your_move())
        {
            var currently = this.board.get_point(x, y);
            if (currently == CONST.No_Color || (x == this.move_x && y == this.move_y))
            {
                this._click_board_move(x, y);
            }
        }
        else if (this.game_is_scoring)
        {
            var currently = this.board.get_point(x, y);
            if (currently != CONST.No_Color)
            {
                this._click_board_score(x, y);
            }
        }
        // else do nothing -- nothing can be done!
    },

    _click_board_speculate : function(x, y)
    {        
    },

    _click_board_move : function(x, y)
    {
        if (this.move_x != -1)
        {
            this.board.clear_point(this.move_x, this.move_y);
            this.board_view.update_dom_at(this.move_x, this.move_y);

            if (x == this.move_x && y == this.move_y)
            {
                // clear the move message
                this._set_move_message_for_no_piece();
                
                // just flip it off!
                this.move_x = -1;
                this.move_y = -1;
                return;
            }
        }

        this.move_x = x;
        this.move_y = y;
        this.board.set_point(x, y, this.your_color, CONST.No_Color, true);
        this.board_view.update_dom_at(x, y);
        this._set_move_message_for_one_piece();
    },

    _click_board_score : function(x, y)
    {
        if (this.you_are_done_scoring) {
            return
        }

        if (this.move_x != -1 || this.move_y != -1) {
            return
        }

        this.move_x = x;
        this.move_y = y;
        var point = this.board.get_point(x, y);
        this.previous_owner = this.board.get_owner(x, y);

        var owner = CONST.No_Color;
        if (this.previous_owner == CONST.No_Color) {
            owner = opposite_color(point);
        }

        this.board.set_point(x, y, point, owner, true);
        this.board_view.update_dom_at(x, y);
        this.mark_stone(owner);
    },

    i_hate_trailing_commas : function() {}
});


//-----------------------------------------------------------------------------
// History Controller (for sailing the seas of time)
//-----------------------------------------------------------------------------

var HistoryCacheItem = Class.create({
    initialize : function()
    {
        this.is_cached = false;
    },

    save : function(board_state_string, white_stones_captured, black_stones_captured, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move)
    {
        this.board_state_string    = board_state_string;
        this.white_stones_captured = white_stones_captured;
        this.black_stones_captured = black_stones_captured;
        this.last_move_message     = last_move_message;
        this.last_move_x           = last_move_x;
        this.last_move_y           = last_move_y;
        this.last_move_was_pass    = last_move_was_pass;
        this.whose_move            = whose_move;
        this.is_cached = true;
    },
    
    i_hate_trailing_commas : function() {}
});

var HistoryCache = Class.create({
    initialize : function(max_move_number)
    {
        this.max_move_number = -1;
        this.items = new Array();
        this.update_max_move_number(max_move_number);
    },

    update_max_move_number : function(max_move_number)
    {
        if (max_move_number > this.max_move_number) {
            for (var i = this.max_move_number + 1; i <= max_move_number; i++) {
                this.items[i] = new HistoryCacheItem();
            }
            this.max_move_number = max_move_number;
        }
    },

    has_move : function(move_number)
    {
        if (isNaN(move_number) || move_number < 0 || move_number > this.max_move_number)
            return false;
        return this.get_move(move_number).is_cached;
    },

    get_move : function(move_number)
    {
        return this.items[move_number];
    },
    
    i_hate_trailing_commas : function() {}
});

var HistoryController = Class.create({            
    initialize : function(your_cookie, your_color, board_size_index, board_state_string, white_stones_captured, black_stones_captured, current_move_number, max_move_number, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move, show_grid)
    {
        this.your_cookie = your_cookie;
        this.your_color = your_color;

        var self = this;

        this.board = new GameBoard(board_size_index);
        this.board.set_from_state_string(board_state_string);
        this.board_view = new GameBoardView(this, this.board, function(e, x, y) { self._click_board(e, x, y); }, show_grid);

        this.max_move_number = max_move_number;
        this.current_move_number = current_move_number;
        this.next_move_number = current_move_number;

        // Sync with the DOM to avoid a funny reload interaction.
        this.sync_move_number();

        this.cache = new HistoryCache(max_move_number);
        this._save_move(current_move_number, max_move_number, board_state_string, white_stones_captured, black_stones_captured, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move);

        this.last_move_message = last_move_message;
        this.last_move_x = last_move_x;
        this.last_move_y = last_move_y;
        this.last_move_was_pass = last_move_was_pass;
        this.whose_move = whose_move;        

        // hack to make IE happy (since the POS ignores initial inline opacity values)
        this.is_loading = true;
        this._stop_loading();

        if (!last_move_was_pass)
        {
            this._hide_pass();
            this.board_view.force_blink_at(this.last_move_x, this.last_move_y);
        }
        else
        {
            this._show_pass();
        }
    },

    //--------------------------------------------------------------------------
    // controller callbacks
    //--------------------------------------------------------------------------    

    first : function()
    {
        this.set_move_number(0);
    },

    rewind : function()
    {
        this.set_move_number(this.next_move_number - 1);
    },

    fast_forward : function()
    {
        this.set_move_number(this.next_move_number + 1);
    },

    last : function()
    {
        this.set_move_number(this.max_move_number);
    },

    goto_move : function()
    {
        new_move = parseInt($("current_move_number").value, 10);
        this.set_move_number(new_move);
    },
    
    update_next_move_number : function(new_number)
    {
        this.next_move_number = new_number;
        this.sync_move_number();
    },

    sync_move_number : function()
    {
        $("current_move_number").value = this.next_move_number;
    },

    set_move_number : function(new_number)
    {
        if (isNaN(new_number) || new_number < 0 || new_number > this.max_move_number) {
            this.sync_move_number();
            return;
        }

        if (this.next_move_number == new_number)
            return;

        this.update_next_move_number(new_number);

        // Check the cache...
        if (this.cache.has_move(new_number))
            this.update_move_number();
        else
            this.retrieve_move_number(new_number);
    },

    update_max_move_number : function(max_move_number)
    {
        if (max_move_number > this.max_move_number) {
            this.max_move_number = max_move_number;
            this.cache.update_max_move_number(max_move_number);
            $("max_move_number").update(max_move_number.toString());
        }
    },

    update_move_number : function()
    {
        if (this.next_move_number == this.current_move_number) { return; }

        // Save this.next_move_number in a local variable to avoid race
        // conditions.
        var next_move_number = this.next_move_number;

        var move = this.cache.get_move(next_move_number);
        this.board.set_from_state_string(move.board_state_string);
        this.board_view.update_dom();

        $("white_stones_captured").update(move.white_stones_captured.toString());
        $("black_stones_captured").update(move.black_stones_captured.toString());

        this.current_move_number = next_move_number;

        this.last_move_message = move.last_move_message; /* TODO anything we can do with this? */

        this.last_move_x = move.last_move_x;
        this.last_move_y = move.last_move_y;
        this.last_move_was_pass = move.last_move_was_pass;
        if (!move.last_move_was_pass)
        {
            this._hide_pass();
            this.board_view.force_blink_at(move.last_move_x, move.last_move_y);
        }
        else
        {
            this._show_pass();
            this.board_view.cancel_blink();
        }
        
        this.whose_move = move.whose_move; /* TODO anything we can do with THIS? */
    },

    //--------------------------------------------------------------------------
    // accessor methods to get at information about the board
    //--------------------------------------------------------------------------

    get_point_name : function(x, y)
    {
        return this.board_view.point_name(x, y);
    },
    
    get_board_width : function()
    {
        return this.board.get_width();
    },

    get_board_height : function()
    {
        return this.board.get_height();
    },

    get_board_view : function()
    {
        return this.board_view;
    },
    
    //--------------------------------------------------------------------------
    // board click callbacks
    //--------------------------------------------------------------------------    

    _click_board : function(e, x, y)
    {
        if (e.shiftKey && e.shiftKey == 1)
        {
            this._selected_square(x, y);
        }
        // else do nothing -- nothing can be done!
    },

    _selected_square : function(x, y)
    {
        var name = history_controller.get_board_view().point_name(x, y);        
        this.board_view.force_blink_at(x, y);
        chat_controller.paste_text(name + " ");
    },

    //--------------------------------------------------------------------------
    // ajax state callbacks
    //--------------------------------------------------------------------------    

    retrieve_move_number : function(new_number)
    {
        if (isNaN(new_number)) { return; }
        if (new_number < 0) { return; }
        if (new_number > this.max_move_number) { return; }

        var self = this;
        this._start_loading();
        new Ajax.Request(
            "/service/get-historical-state/",
            {
                method: 'POST',

                parameters:
                {
                    "your_cookie": this.your_cookie,
                    "move_number": new_number
                },

                onSuccess : function(transport)
                {
                    self._stop_loading();
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        self._hide_error();
                        self._save_move
                        (
                            response['current_move_number'],
                            response['max_move_number'],
                            response['board_state_string'],
                            response['white_stones_captured'],
                            response['black_stones_captured'],
                            response['last_move_message'],
                            response['last_move_x'],
                            response['last_move_y'],
                            response['last_move_was_pass'],
                            response['whose_move']
                        );
                    }
                    else
                    {
                        self._display_error(response['flash']);
                        self._check_number_after_error(new_number);
                    }
                },

                onFailure : function()
                {
                    self._stop_loading();
                    self._display_error("Sorry, but an unexpected error occured. Try again later.");
                    self._check_number_after_error(new_number);
                }
            }
        );        
    },

    _save_move : function(move_number, max_move_number, board_state_string, white_stones_captured, black_stones_captured, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move)
    {
        this.update_max_move_number(max_move_number);
        this.cache.get_move(move_number).save(board_state_string, white_stones_captured, black_stones_captured, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move);
        if (this.next_move_number == move_number)
            this.update_move_number();
    },

    _check_number_after_error : function(new_number)
    {
        // Only reset the move numbers of "new_number" is the next one to
        // display.
        if (this.next_move_number == new_number)
            update_next_move_number(this.current_move_number);
    },

    _display_error : function(message)
    {
        $("history_error").update(message);
        $("history_error").removeClassName("hide");        
    },

    _hide_error : function()
    {
        $("history_error").update("&nbsp;");
        $("history_error").addClassName("hide");
    },

    _hide_pass : function()
    {
        $("last_pass").addClassName("hide");
    },

    _show_pass : function()
    {
        $("last_pass").removeClassName("hide");
    },
    
    
    //--------------------------------------------------------------------------
    // ajax notification (TODO -- uncopy this code)
    //--------------------------------------------------------------------------    
    
    _start_loading : function()
    {
        if (this.is_loading) { return; }

        this.is_loading = true;
        new Effect.Opacity("loading", {to: 1.0, duration: 0.2});
    },

    _stop_loading : function()
    {
        if (!this.is_loading) { return; }
        
        this.is_loading = false;
        new Effect.Opacity("loading", {to: 0.0, duration: 0.2});                        
    },
    
    i_hate_trailing_commas : function() {}
});


//-----------------------------------------------------------------------------
// Options Controller
//-----------------------------------------------------------------------------

var OptionsController = Class.create({
    initialize : function(your_cookie, your_email, your_twitter, your_contact_type)
    {
        this.your_cookie = your_cookie;
        this.your_email = your_email;
        this.your_twitter = your_twitter;
        this.your_contact_type = your_contact_type;       

        if (this.your_contact_type == CONST.No_Contact)
        {
            // make IE6 and IE7 happy
            new Effect.Opacity("contact_info_container", {to: 0.0, duration: 0.1});
        }

        this.is_valid = false;
        this.is_save_active = false;
        this.is_finished = false;
        this.showing_twitter_password = false;

        $("contact_info").observe('keyup', this._keyup_contact_info.bindAsEventListener(this));
    },

    rotate_contact_type : function()
    {
        if (this.is_finished) { return; }
        
        if (this.your_contact_type == CONST.Email_Contact)
        {
            this.your_email = $("contact_info").value;
            this.your_contact_type = CONST.Twitter_Contact;
            $("rotate_link").update("notify me via twitter");
            $("contact_info_label").update("Your twitter:");
            $("contact_info").value = this.your_twitter;
        }
        else if (this.your_contact_type == CONST.Twitter_Contact)
        {
            this.your_twitter = $("contact_info").value;
            this.your_contact_type = CONST.No_Contact;
            $("rotate_link").update("don&#146;t send me any notification");
            new Effect.Opacity("contact_info_container", {to: 0.0, duration: 0.2});
        }
        else
        {
            this.your_contact_type = CONST.Email_Contact;
            $("rotate_link").update("notify me via email");
            $("contact_info_label").update("Your email:");
            $("contact_info").value = this.your_email;
            new Effect.Opacity("contact_info_container", {to: 1.0, duration: 0.2});
        }

        this._hide_twitter_password();
        this._update_validity();
    },

    save_options : function()
    {
        if (!this.is_valid) { return; }

        var self = this;
        var params = {
            "your_cookie": this.your_cookie,
            "new_contact_type": this.your_contact_type
        };

        if (this.your_contact_type == CONST.Twitter_Contact)
        {
            params["new_contact"] = this.your_twitter;
        }
        else if (this.your_contact_type == CONST.Email_Contact)
        {
            params["new_contact"] = this.your_email;
        }

        if (this.showing_twitter_password)
        {
            var tp = $("twitter_password").value;
            if (tp && tp.length > 1)
            {
                params["your_twitter_password"] = tp;
            }
        }

        new Ajax.Request(
            "/service/change-options/",
            {
                method: 'POST',
                parameters: params,

                onSuccess: function(transport)
                {
                    var response = eval_json(transport.responseText);
                    if (response['success'])
                    {
                        if (response['need_your_twitter_password'])
                        {
                            self._require_twitter_password(response['flash']);
                        }
                        else
                        {
                            self._succeed_save_options();
                        }
                    }
                    else
                    {
                        self._fail_save_options(response['flash']);
                    }
                },

                onFailure: function()
                {
                    self._fail_save_options("Sorry, but an unknown failure occured. Please try again.");
                }
            }
        );
        
    },

    _succeed_save_options : function()
    {
        this.is_finished = true; /* success! */
        this._hide_twitter_password();
        $("flash").update("Your options were updated successfully.");
        Effect.Appear("flash");
        $("save_p").addClassName("hide");
        $("cancel_p").addClassName("hide");
        $("back_p").removeClassName("hide");
        $("rotate_link").removeClassName("subtle-link");
        new Effect.Opacity("contact_info_container", {to: 0.0, duration: 0.2});
    },

    _fail_save_options : function(flash)
    {
        $("flash").update(flash);        
        Effect.Appear("flash");
        this._hide_twitter_password();        
    },

    _show_twitter_password : function()
    {
        if (this.showing_twitter_password) { return; }
        $("twitter_password_container").removeClassName("hide");
        this.showing_twitter_password = true;
    },

    _hide_twitter_password : function()
    {
        if (!this.showing_twitter_password) { return; }
        $("twitter_password_container").addClassName("hide");
        $("flash").update("");
        this.showing_twitter_password = false;
    },
    
    _require_twitter_password : function(flash)
    {
        this._show_twitter_password();
        $("flash").update(flash);
        Effect.Appear("flash");
    },

    _keyup_contact_info : function()
    {
        if (this.is_finished) { return; }
        
        if (this.your_contact_type == CONST.Email_Contact)
        {
            this.your_email = $("contact_info").value;
            this._update_validity();
        }
        else if (this.your_contact_type == CONST.Twitter_Contact)
        {
            this.your_twitter = $("contact_info").value;
            this._update_validity();
        }
    },

    _update_validity : function()
    {
        this.is_valid = false;
        if (this.your_contact_type == CONST.Email_Contact)
        {
            this._update_email_validity();
        }
        else if (this.your_contact_type == CONST.Twitter_Contact)
        {
            this._update_twitter_validity();
        }
        else
        {
            this.is_valid = true;
        }

        if (this.is_valid)
        {
            this._activate_save();
        }
        else
        {
            this._deactivate_save();
        }
    },

    _update_email_validity : function()
    {
        this.is_valid = ContactValidator.is_probably_good_email(this.your_email);
    },

    _update_twitter_validity : function()
    {
        this.is_valid = ContactValidator.is_probably_good_twitter(this.your_twitter);
    },

    _activate_save : function()
    {
        if (this.is_save_active) { return; }
        $("save_link").removeClassName("disabled");
        this.is_save_active = true;
    },

    _deactivate_save : function()
    {
        if (!this.is_save_active) { return; }
        $("save_link").addClassName("disabled");
        this.is_save_active = false;
    },
    
    i_hate_trailing_commas : function() {}
});


//-----------------------------------------------------------------------------
// Database Update Controller
//-----------------------------------------------------------------------------

var DatabaseUpdateController = Class.create({
    initialize : function()
    {
        this.updating_database = false;
    },

    ensure_reminder_times : function()
    {
        if (this.updating_database) { return; }
        this._start_updating();

        this.total_found = 0;
        this.total_modified = 0;
        this._inner_ensure_reminder_times(null, 5);
    },

    _inner_ensure_reminder_times : function(last_id_seen, amount)
    {
        var self = this;

        var parameters = {};
        parameters["amount"] = amount.toString();
        if (last_id_seen != null)
        {
            parameters["last_id_seen"] = last_id_seen.toString();
        }
                
        new Ajax.Request
        (
            "/cron/ensure-reminder-times/",
            {
                method: 'POST',
                parameters: parameters,
                
                onSuccess: function(result)
                {
                    var json = eval_json(result.responseText);
                    if (json['success'])
                    {
                        self._handle_ensure_url_response(amount, json['amount_found'], json['amount_modified'], json['new_last_id']);
                    }
                    else
                    {
                        self._stop_updating();
                        alert("Queue updating failed. Please try again. Error: " + json['Error']);
                    }
                },

                onFailure: function()
                {
                    self._stop_updating();
                    alert("Database update network request failed. Please try again.");
                }
            }
        );
    },

    _handle_ensure_url_response : function(amount, amount_found, amount_modified, new_last_id)
    {
        this.total_found += amount_found;
        this.total_modified += amount_modified;
        if (amount_found > 0)
        {
            $("updating").innerHTML = "UPDATING: Modified " + this.total_modified.toString() + " out of " + this.total_found.toString() + ".";
            this._inner_ensure_reminder_times(new_last_id, amount);            
        }
        else
        {
            this._stop_updating();
            alert("Finished Updating! Modified " + this.total_modified.toString() + " out of " + this.total_found.toString() + ".");
        }
    },
    
    _start_updating : function()
    {
        this.updating_database = true;
        $("updating").removeClassName("hide");
    },

    _stop_updating : function()
    {
        $("updating").addClassName("hide");
        this.updating_database = false;
    }
});


//-----------------------------------------------------------------------------
// Initialization And Globals
//-----------------------------------------------------------------------------

var get_going = null;
var game_controller = null;
var chat_controller = null;
var history_controller = null;
var options_controller = null;
var database_update_controller = null;

function init_get_going()
{
    fill_from_query_string($('game_form'));
    get_going = new GetGoing();    
}

function init_play(your_cookie, your_color, current_move_number, whose_move, board_size_index, board_state_string, white_stones_captured, black_stones_captured, your_name, opponent_name, opponent_contact, opponent_contact_type, wants_email, last_move_x, last_move_y, last_move_was_pass, you_are_done_scoring, opponent_done_scoring, scoring_number, game_is_scoring, you_win, opponent_wins, game_is_finished, last_move_message, show_grid)
{
    game_controller = new GameController(your_cookie, your_color, current_move_number, whose_move, board_size_index, board_state_string, white_stones_captured, black_stones_captured, your_name, opponent_name, opponent_contact, opponent_contact_type, wants_email, last_move_x, last_move_y, last_move_was_pass, you_are_done_scoring, opponent_done_scoring, scoring_number, game_is_scoring, you_win, opponent_wins, game_is_finished, last_move_message, show_grid);
    chat_controller = new ChatController(your_cookie, false);
    chat_controller.start_listening_to_chat();
}

function init_history(your_cookie, your_color, board_size_index, board_state_string, white_stones_captured, black_stones_captured, max_move_number, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move, show_grid)
{
    history_controller = new HistoryController(your_cookie, your_color, board_size_index, board_state_string, white_stones_captured, black_stones_captured, max_move_number, last_move_message, last_move_x, last_move_y, last_move_was_pass, whose_move, show_grid);
    chat_controller = new ChatController(your_cookie, true);
    chat_controller.start_listening_to_chat();
}

function init_options(your_cookie, your_email, your_twitter, your_contact_type)
{
    options_controller = new OptionsController(your_cookie, your_email, your_twitter, your_contact_type)
}

function init_database_update()
{
    database_update_controller = new DatabaseUpdateController();
}
