# The Game Of Go

## Introduction

### What is this? (Short Version)

https://go.davepeck.org/

This is a website that lets people learn and play the ancient game of Go in an elegant way.

It's currently a Webapp2 site, using Python 2.7, targeted for hosting with Google App Engine. It's open source under the MIT license.

You can see the latest bits running at http://go.davepeck.org/ -- I will always run them there, on my own dime.


### What is this? (Longer Version)

Currently, this service lets you set up a game of Go with a friend. There are no logins or passwords. When it's your turn, you get an email notification. Or, you can silence email and just leave your browser window open. It will update automatically when it's time for you to move.

If you're new to the game of Go, you might consider reading the excellent tutorial at http://is.gd/kD5q

I originally wrote this code as a "weekend hack": a fun project that I could get to a reasonable degree of polish in about a weekend, and that would be a useful "learning" code base for a new technology (in this case, App Engine.) Since that first weekend, I've added chat and a history view. But there is still a lot more to do. There are lots of cool features I'd love the community to work on. I've listed some below; I'm sure you'll have other even better ideas. Also, because I wrote this software as fast as I could, the code is a rough around the edges. No doubt you will see all sorts of oddities as you look through it; feel free to just help get the service on a more solid footing!

Anyway, dive in and enjoy. With a little work, I bet we can turn this project into the best place to play Go on the internets!

### What's the current status?

**June 18, 2013**. I built this website in 2009. Now, in 2013, _tons_ of people use it every day to learn and play go!

So: I'm doubling down. I've got lots of exciting things in mind for the site, but the core mission will remain the same:

> Be the best place to learn to play Go on the Internet.

There's a lot of technical debt to overcome, first. My immediate next steps are as follows:

- <span style="text-decoration: line-through;">Update to Python 2.7 (and the modern App Engine Python APIs)</span>
- <span style="text-decoration: line-through;">Move the application to the App Engine HRD</span>
- Move from webapp2 to a modern version of Django (1.4 or 1.5 if GAE lets me.)
- Completely port away from App Engine and onto a bog-standard Django install.
- Rip out prototype & scriptaculous and replace with jQuery (and coffeescript) in a first pass
- Properly separate back-end concerns (right now game, game history, players, etc. are oddly intermixed)
- Properly separate front-end concerns (right now lots of javascript there is a jumble)
- Rewrite the front-end script entirely and get it on a firm footing
- Move to SASS
- Fix CSS and HTML so that the website looks great on mobile devices
- Separate concerns so that there is a proper API that native apps can access
- Improve the "create game" flow so options are obvious
- Get twitter working again, maybe.

As this is a hobby project, I expect these initial efforts will take quite some time. They will be incremental, though, so the site will continue to behave well as each change is made.

## Exploring The Code

At the moment there isn't too much code. It's a big messy ball of spaghetti (but see plans above.)

The key files are:

- `go.py`: currently houses all of the AppEngine server-side code, and all of the logic needed to play go (like liberty counting, Ko detection, etc.)
- `static/js/go.js`: currently houses all of the browser javascript code, including visuals and AJAX communication
- `static/css/go.css`: a total mess of a CSS file for the service.
- `templates/play.html` and `templates/history.html`: these are the two "main" pages. the templates are a little gnarly at the moment.
- `templates/get-going.html`: the game "creation" form


## Community Contributions To Date

This is an open source, community-driven project. Lots of people have added great things, including:

- Support for the SGF Go file format. (Thanks to Emil Sit! -- "sit" on github)
- Support for chat in the SGF Go file format. (Thanks again, Emil.)
- Support for notification via twitter. (A suggestion of Ray Krueger. Dave Peck implemented it.)
- Lots of new chat features and improvements, including:
  1. Ability to see the full chat history.
  2. Ability to refer to specific board squares when chatting. For example, "Dude, you should have moved at A11." will show up with "A11" underlined; clicking on it will cause that grid square to flash.
  3. Ability to easily figure out board square names and get them into the chat box.
  4. Auto-linkification of valid http, https, and ftp URLs.
- Make all pages fully XHTML 1.0 STRICT valid, according to the W3C validator.


## Cool stuff I'd love to see people work on

There is a LOT of stuff to do here, so dive in! I'm open to all suggestions and patches. Send 'em my way.

This list is in "no particular order":

- **User accounts**: I want to make sure that people can continue to use the service without ever having to create an account, choose a password, or login. That said, there are some power users who play many games at once. For them, I want to make sure they can log in and track all their games in one central place.
- **Ranks, user profiles, and other social features**: I think community aspects are ultimately important in any single-game site like this
- **UI Improvements**: I'm not a designer. I tried to make things simple, but I think there's probably lots of room for improvement, both visually and in terms of the interaction model. I'll leave this open-ended and see what people come up with.
- **Game branching and speculation**: I'd like people to be able to look through the history of a game and then "branch" it where some critical move was made, so they can try a new path.
- **Chat improvement**: At the moment, when you chat, the internal representation ties what you said to a particular move. But I don't expose this in the UI anywhere. It would be helpful!
- **Better layout for 9x9 and 13x13 games**: Right now the gameplay visual layout is designed with the 19x19 board size in mind. The chat area, in particular, looks wonky on smaller boards. This is one specific "UI Imprvoement" that's probably worth calling out.
- **Facebook integration**: Not sure about this, but perhaps some people would use it?
- **Code cleanup**: (!) I wrote this service as a "weekend hack." As a result, there are lots of strange things still in there. Many data structures, local variables, etc. are either extraneous, or duplicated, or something in between. I had the idea that I would do true MVC on the javascript side. The "models" would directly parallel python types on the back end. The views were just about managing visual appearance. And the controllers tied them together. I got partway there, because frankly it just wasn't important to keep this separation when doing a three day hack. I'd like to go back and really clean this stuff up now. Check out go.js for details. The "service" URLs are a bit of a mess. I originally wrote one to check to see if your opponent moved, but what I really should have is a single unified "get state" POST request that takes the desired move number and returns the state. It should work for history as well as game play. I want this in-part for cleanliness, in-part because I think it will make implementing an iPhone front-end easier.
- **Make it look better in IE9+**: For example, I use :hover CSS pseudo-classes on a bunch of non-anchor-tags. That's an IE no-no, but I did it anyway.
- **Clean up CSS**: This is madness.
- **Documentation**: Y'know, python docstrings, etc. Like a real piece of software.
- **Tests**: Y'know, like a real piece of software.


## Licenses

Dave Peck's Go is (c) 2009-2013 Dave Peck, All Rights Reserved. It is licensed under the MIT license. (It used to be licensed under the uber-restrictive AGPLv3 but that was kinda silly, no?)

There are a few other bits of code included; they all happen to be MIT-licensed too:

1. The simplejson library is licensed under an MIT License. A number of people have contributed. You can find out more here: http://code.google.com/p/simplejson/
2. The prototype.js library is (c) 2005-2008 Sam Stephenson and is also under an MIT License.
3. The scriptaculous javascript libraries are (c) 2005-2008 Thomas Fuchs, also under an MIT License.

As for the graphics:

1. All of the images used in the main game board are modified versions of files I found on the Wikimedia Commons. These are distributed with the Creative Commons Attribution 2.0 ShareAlike license. Unfortunately, I can't figure out who made them originally -- the user name is Micheletb
2. All remaining images were hand-drawn by me. I hereby put them under the Creative Commons Attribution ShareAlike 2.0 license: http://creativecommons.org/licenses/by-sa/2.0/



