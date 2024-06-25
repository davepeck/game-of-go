
Board state string
==================

There are now seven possible board states for a given coordinate:
 - no stone;
 - no stone, black's territory;
 - no stone, white's territory;
 - black stone;
 - black stone, white's territory (dead black stone);
 - white stone;
 - white stone, black's territory (dead white stone).

The _GameBoard_ class in 'go.js' needs to track this stuff.  I plan to add an
_owner_ field that's parallel to 'board', storing 'black', 'white', or 'none'
for each position.  This implies another two states:
 - black stone, black's territory;
 - white stone, white's territory.

I'm not sure whether these two states should be used in someway, or just be
considered invalid.  I'm leaning towards invalid.

The _state_string_ representing the board state needs to deal with the new
states.  These make sense to me:

|==================================
| '.' | no stone
| 'B' | no stone, black's territory
| 'W' | no stone, white's territory
| 'b' | black stone
| 'c' | black stone (dead)
| 'w' | white stone
| 'x' | white stone (dead)
|==================================

'c' and 'x' were chosen just because they follow 'b' and 'c' in the alphabet.

Scoring algorithms
==================

Algorithm for counting territory, given:
 - komi,
 - the number of black stones captured during the game,
 - the number of white stones captured during the game,
 - the coordinates of live black stones,
 - the coordinates of live white stones,
 - the number of dead black stones on the board, and
 - the number of dead white stones on the board.

 1. Mark live black stones with 'b', live white stones with 'w', and all other
    coordinates with '?'.
 2. For each coordinate '?':
    - Search in all directions, stopping at any 'b' or 'w'.
    - If both 'b' and 'w' coordinates are found, then mark all '?' with '.'.
    - If only 'b' coordinates are found, then mark all '?' with 'B'.
    - If only 'w' coordinates are found, then mark all '?' with 'W'.
 3. Black's territory is the sum of:
    - the number of coordinates marked 'B',
    - the number of white stones captured during the game, and
    - the number of dead white stones on the board.
 4. White's territory is the sum of:
    - komi,
    - the number of coordinates marked 'W',
    - the number of black stones captured during the game, and
    - the number of dead black stones on the board.

Algorithm for finding other dead stones, given:
 - the coordinate of the new dead stone,
 - the coordinates of all stones of the same colour, and
 - the coordinates of the live stones of the other colour.

 1. Mark the stones of the same colour with '?', the live stones of the other
    colour with 'a' (for alive), and all other coordinates with '.'.
 2. From the new dead stone, search in all directions, stopping at any
    'a'.  Mark all '?' encountered as 'd' (for dead).

Planned flow for marking dead stones
====================================

 1. After two consecutive passes, the playing board is used for scoring.
    - The player that passed first gets an email announcement.
    - Both players are able to mark dead stones.
    - The link _done_ appears, and is enabled.
    - Next to the _done_ link, there is some _opponent_done_ text; perhaps,
      '(opponent has clicked done)'.  This text is initially hidden.
 2. Clicking _done_ sends the board state to the server.
    - A confirmation dialog is required.  This helps with any race conditions:
      if an update has *just* been received from the opponent, this player will
      have a chance to notice.
    - The opponent gets an email.
    - The server stores the final board state for that user.
    - If the opponent has already clicked _done_ and the final board states
      match, then the game is over.
    - If the opponent has already clicked _done_ and the final board states *do
      not* match, then there has been a race condition (as should be evident
      after reading further)... hopefully, this situation is avoidable.
    - If the opponent has *not* already clicked _done_, then their
      _opponent_done_ text is shown on their next update.
    - The _done_ link is disabled.
 3. Clicking a stone on the board (either dead or alive) will send that stone
    to the server.
    - Send the coordinates of the stone that was clicked, as well as the
      supposed new owner.
    - The server saves the state of the stone, and sends back the new board
      state.
    - This is completed without link confirmation, since it can be undone... no
      need for the stupid-proof API used when playing the game.
    - If the opponent had previously clicked _done_, then the opponent's final
      board state is cleared, the opponent receives an email, and this player's
      _opponent_done_ text is hidden again.
 4. Periodically, the UI polls the server for updates.

Details of client-side state transitions during scoring
=======================================================

There are lots of client-side bugs in the UI, so I'm going to get more
specific.
 - _has_opponent_moved_ request succeeds
   - _you_have_passed_        ->  _scoring_
     - Occurs when opponent clicks _pass_ after you.
     - Hide the links about passing, etc., and show the _done_ link.
     - Show initial territory calculations.
   - other possibilites not relevant.
 - you click _pass_
   - _has_opponent_passed_    ->  _scoring_
     - Occurs when you click _pass_ after opponent.
     - Hide the links about passing, etc., and show the _done_ link.
     - Show initial territory calculations.
   - other possibilites not relevant.
 - you _mark_stone_
   - _scoring_                ->  _scoring_
     - Occurs when you mark a group of stones.
     - May incorporate changes from opponent as well.
     - Update territory calculations.
   - _opponent_is_done_       ->  _scoring_
     - Occurs when you mark a group of stones.
     - Update the territory calculations.
 - you click _done_
   - _scoring_                ->  _scoring_
     - Occurs when you click _done_, but the server has a _scoring_number_
       higher than the one sent in.
     - Update the territory calculations.
     - Update _scoring_number_.
   - _scoring_                ->  _you_are_done_
     - Occurs when you click _done_, and the server has the same
       _scoring_number_.
     - Disable the _done_ link.
   - _opponent_is_done_       ->  _game_finished_
     - Occurs when you click _done_.
     - Hide the _done_ link.
     - Display game over text.
 - _has_opponent_scored_ request succeeds
   - _scoring_                ->  _scoring_
     - Occurs when opponent _mark_stone_.
     - Update territory calculations.
     - Update _scoring_number_.
   - _scoring_                ->  _opponent_is_done_
     - Occurs when opponent clicks _done_.
     - Update territory calculations, since opponent may have used
       _mark_stone_.
     - Update _scoring_number_.
   - _you_are_done_           ->  _scoring_
     - Occurs when opponent _mark_stone_.
     - Enable the _done_ link.
     - Update the territory calculations.
     - Update _scoring_number_.
   - _you_are_done_           ->  _opponent_is_done_
     - Occurs when opponent _mark_stone_ and then clicks _done_.
     - Enable the _done_ link.
     - Update territory calculations.
     - Update _scoring_number_.
   - _you_are_done_           ->  _game_finished_
     - Occurs when opponent clicks _done_.
     - Hide the _done_ link.
     - Display game over text.

// vi: set ft=asciidoc:
