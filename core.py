__author__ = 'thorvald'
from collections import namedtuple
import curses
from itertools import product,chain
import re
from random import choice, randrange
import json
from textwrap import wrap

Command = namedtuple("Command", "matches,arguments,function")

Commandlist = []
chartrimmer = re.compile("[^a-zA-Z0-9 ]")
spacer = re.compile(" +")

def add_command(matches, arguments=""):
    def decorator(function):
        Commandlist.append(Command(matches, arguments, function))
        return function

    return decorator


class CommandInterpreter:
    def __init__(self, interface, gamestate):
        self.interface = interface
        self.gamestate = gamestate

    def do_next_command(self):
        self.handle_command(self.interface.get_command())

    def handle_command(self, command:str):
        command = chartrimmer.sub("", command).lower()
        if command:
            key, *args = command.split(" ")
            self.read_command(key, *args)

    def read_command(self, *words):
        ERROR = ["The system does not know what you mean by that."]
        skip = {"from", "with", "at", "a", "the", "this", "that", "those", "my"}
        words = [x for x in words if x not in skip]
        for c in Commandlist:
            valid = False
            compare = c.matches.split("|")
            for key in compare:
                if words[0] == key:
                    valid = True
                    break
            if not valid:
                continue
            key, *args = words
            argsobjs = {}
            argsobjs["d"] = self.extract_directions(args)
            argsobjs["e"] = self.gamestate.extract_entities(args)
            argsobjs["i"] = self.gamestate.extract_inventory(args)
            argsobjs["l"] = self.gamestate.extract_loot(args)
            info = {"d": "direction", "e": "target entity", "i": "target item (inventory)",
                    "l": "target item (in world)"}
            command_param = []
            default_argument = False

            for s in c.arguments:
                if s == "!":
                    default_argument = True
                    continue
                try:
                    command_param.append(next(argsobjs[s]))
                except StopIteration:
                    if not default_argument:
                        ERROR += ["The command '{}' is missing some details regarding {}."\
                                  .format(key, info.get(s, "<<invalid>>")).replace("\n",""),
                                  "It could be simply missing but it could also be invalid."]


                        break
            else:
                c.function(self, *command_param)
                break
        else:
            self.interface.send_message("The system has trouble interpreting your command.")
            for e in ERROR:
                self.interface.send_message(e)

    def extract_directions(self, wordlist):
        for w in wordlist:
            if w in ("north", "east", "south", "west"):
                yield w

    @add_command("go|walk|run|travel", "d")
    def travel(self, direction):
        self.gamestate.travel(direction)
        #self.gamestate.end_turn()

    @add_command("clear|reset", "")
    def clear(self):
        self.interface.stdscr.clear()
        self.look()

    @add_command("enter", "e")
    def enter(self, building):
        if isinstance(building, Building):
            self.gamestate.enter_building(building)
        else:
            self.interface.send_message("You cannot enter a not building")

    @add_command("exit", "")
    def exit(self):
        self.gamestate.exit_building()

    @add_command("loot|pick|get|empty", "e")
    def loot(self, entity):
        if isinstance(entity, Lootable):
            entity.loot()
        else:
            self.interface.send_message("You cannot loot this object")
        self.gamestate.end_turn()

    @add_command("loot|pick|get", "l")
    def loot(self, tupl):
        entity,item = tupl
        if isinstance(entity, Lootable):
            entity.loot(item)
        else:
            self.interface.send_message("You cannot loot this object")
        self.gamestate.end_turn()

    @add_command("hit|attack|kill|stab|swing|trust|chop|bash", "e!i")
    def attack(self, entity, item=None):
        entity.attack(item)
        self.gamestate.end_turn()

    @add_command("inspect|study|analyse", "e")
    def inspect(self, entity):
        entity.inspect()

    @add_command("look|where", "")
    def look(self):
        self.gamestate.local_desciption()

    @add_command("buy|trade", "l")
    def buy(self,tupl):
        entity,item = tupl
        if isinstance(entity, Shopkeeper):
            entity.buy(item)
        else:
            self.interface.send_message("You cannot buy this object")
        self.gamestate.end_turn()


    @add_command("sell", "ei")
    def buy(self,entity,item):
        if isinstance(entity, Shopkeeper):
            entity.sell(item)
        else:
            self.interface.send_message("You cannot sell to this person")
        self.gamestate.end_turn()

class Interface:
    def __init__(self):
        self.stdscr = curses.initscr()
        self.messagehist = []

    def __enter__(self):
        # if extra settings for the window are needed, put them here
        self.stdscr.scrollok(True)
        return self

    def __exit__(self, type, value, traceback):
        # if extra settings for the window are needed, revert them here
        curses.endwin()

    def get_command(self):
        self.stdscr.addstr(">->")
        r = self.stdscr.getstr().decode("utf-8")
        UP = chr(27)+chr(91)+chr(65)
        if UP not in r:
            self.messagehist.append(r)
            return r
        else:
            try:
                return self.messagehist[-r.count(UP)]
            except IndexError:
                return "where"

    def send_message(self, message):
        for m in chain(*(wrap(line) for line in spacer.sub(" ",message).split("\n"))):
            self.stdscr.addstr(m)
            self.newline()

    def newline(self):
        self.stdscr.addstr("\n")
        y,x = self.stdscr.getyx()
        while y >= 19:
            self.stdscr.scroll(1)
            y = y-1
            self.stdscr.move(y,x)


class GameState:
    def __init__(self, interface, language="lang_en.json"):
        self.send_message = interface.send_message
        interpreter = CommandInterpreter(interface, self)
        self.do_next = interpreter.do_next_command
        with open("data.json") as file:
            self.data = json.load(file)
        # with open(language) as file:
        #    self.lang = json.load(file)
        self.currenttile = generate_map_tiles(self, 100)
        self.building_stack = []
        self.player = Player(self.currenttile,"player")

        self.currenttile.send_description()
        self.end_of_turn = False

    @property
    def inventory(self):
        return self.player.contents

    def travel(self, direction):
        if self.building_stack:
            self.send_message("You cannot travel while inside".format(direction))
        if not direction:
            direction = "<empty>"
        if direction in self.currenttile.border:
            self.currenttile = self.currenttile.border[direction]
        else:
            self.send_message("You cannot travel '{}'".format(direction))
        self.currenttile.send_description()

    def local_desciption(self):
        if not self.building_stack:
            self.currenttile.send_description()
        else:
            self.building_stack[-1].send_description()

    def enter_building(self, building):
        self.building_stack.append(building)
        self.local_desciption()

    def exit_building(self):
        if self.building_stack:
            self.building_stack.pop()
        self.local_desciption()

    def get_entities(self):
        if not self.building_stack:
            return sorted(self.currenttile.entities, key=lambda x:x.priority())
        else:
            return sorted(self.building_stack[-1].entities, key=lambda x:x.priority())

    def extract_entities(self, wordlist):
        for w in wordlist:
            if w in {"me","i","myself"}:
                yield self.player
            for e in self.get_entities():
                if e.tagname == w:
                    yield e

    def extract_loot(self, wordlist):
        for w in wordlist:
            for e in self.get_entities():
                if hasattr(e, "contents"):
                    for c in e.contents:
                        if c.name == w:
                            yield e,c

    def extract_inventory(self, wordlist):
        for w in wordlist:
            for e in self.inventory:
                if e.name == w:
                    yield e


    def mainloop(self):
        while True:
            if self.player.active():
                while self.player.active() and not self.end_of_turn:
                    self.do_next()
            else:
                self.send_message("You are to injured to do anything.")
            for e in self.get_entities():
                e.free_action()
            self.player.free_action()
            self.end_of_turn = False

    def end_turn(self):
        self.end_of_turn = True


def tell_list(args):
    args = list(args)
    if not args:
        return "nothing"
    elif len(args) == 1:
        return args[0]
    return ", ".join(args[:-1]) + " and " + args[-1]


class MapTile:
    def __init__(self, parent):
        self.parent = parent
        self.border = {}
        self.name = "invalid area"
        self.entities = []

    def describe(self, version=""):
        if version == "look":
            yield "You see a {} up north".format(self.name)
        else:
            yield "You are in {}.".format(self.name)
            if self.entities:
                yield "You can see {}.".format(tell_list(x.describe() for x in self.entities))
            else:
                yield "There is noting of interest here"

    def send_description(self, version=""):
        for line in self.describe(version):
            self.parent.send_message(line)


class Entity:
    def __init__(self, location, name):
        self.parent = location.parent
        self.location = location
        location.entities.append(self)
        self.name = name
        self.tagname = name.split(" ")[-1]
        self.broken = False
        self.prefixes = [lambda s: "damaged" if s.broken else ""]

    def describe(self, spec_article=""):
        prefixes = ", ".join(k(self) for k in self.prefixes)
        if spec_article:
            article = spec_article
        elif self.name[0] in "aeiou":
            article = "an"
        else:
            article = "a"
        return "{} {} {}".format(article, prefixes, self.name)

    def inspect(self):
        self.send_format("this is {descr}")

    def attack(self, weapon=...):
        self.send_format("you attack {descrt}")
        self.broken = True

    def format_local(self, string):
        return string.format(descr=self.describe(), descrt=self.describe("the"), **self.__dict__)

    def send_format(self, string):
        self.parent.send_message(self.format_local(string))

    def free_action(self):
        """
        This method should be overwritten if entity is alive and should perform something after the player.
        :return: None
        """
        pass

    def priority(self):
        return 0


class Building(Entity):
    def __init__(self, location, name, inside_name=""):
        Entity.__init__(self, location, name)
        self.inside_name = inside_name if inside_name else self.name
        self.entities = []

    def describe_inside(self):
        yield "You are in a {}.".format(self.inside_name)
        if self.entities:
            yield "You can see {}.".format(tell_list(x.describe() for x in self.entities))
        else:
            yield "There is noting of interest here"

    def send_description(self):
        for line in self.describe_inside():
            self.parent.send_message(line)


class Lootable(Entity):
    def __init__(self, location, name):
        Entity.__init__(self, location, name)
        self.contents = []

    def loot_raw(self,piece=None):
        if piece is None:
            self.parent.inventory.extend(self.contents)

            self.send_format("You empty {descrt}. You gain {contains}.")
            self.contents = []
        else:
            if piece in self.contents:
                self.parent.inventory.append(piece)

                self.send_format("You get {} from {{descrt}}.".format(piece.describe()))
                self.contents.remove(piece)

    def loot(self,piece=None):
        self.loot_raw(piece)

    def inspect(self):
        if self.contents:
            self.send_format("This is {descr}. It contains {contains}.")
        else:
            self.send_format("This is {descr}. It is empty.")

    def format_local(self, string):
        return string.format(descr=self.describe(), descrt=self.describe("the"), contains=tell_list(x.describe() for x in self.contents),
                             **self.__dict__)


class Unit(Lootable):
    def __init__(self, location, name):
        Lootable.__init__(self, location, name)
        self.healthnum = 100
        self.healthparam = 3
        self.strength = 10
        self.defence = 0
        self.aggressive = False
        self.prefixes = [Unit.health_descr]

    def health_descr(self):
        return ["death", "unconsiousness", "wounded", ""][self.healthparam]

    def attack(self, weapon=None):
        self.send_format("you attack {descrt}")
        if not self.healthparam:
            self.send_format("He's dead Jim.")
            return
        if not isinstance(weapon, Weapon):
            damage = 10
        else:
            damage = weapon.damage
        if damage <= self.defence:
            self.send_format("You attack {descrt} but it doesn't seem to work.")
        damage -= self.defence
        self.deal_damage(damage)

    def deal_damage(self, damage):
        if damage >= randrange(self.healthnum):
            self.healthparam -= 1
            self.send_format("The attack works")
            self.send_format("{descrt} is now {health}.")
        else:
            self.send_format(choice((
                "The attack missed",
                "The attack was evaded",
                "The attack was parried",
                "The attack was blocked",
                "The attack was caught",
                "The attack only gazes")))
        self.aggressive = True

    def free_action(self):
        if 0 < self.healthparam < 3 and not randrange(200):
            self.healthparam += 1
        if self.active() and self.aggressive:
            self.send_format("You are attacked by {descr}.")
            self.parent.player.deal_damage(self.strength)

    def inspect(self):
        self.send_format("This is {descr}. It is carrying {contains}.")

    def active(self):
        return self.healthparam > 1

    def loot(self,piece=None):

        if not self.active():
            self.loot_raw(piece)
        else:
            self.send_format("You fail to empty the pockets of {descrt}.")
            self.aggressive = True


    def format_local(self, string):
        return string.format(descr=self.describe(), descrt=self.describe("the"),
                             health=self.health_descr(),
                             contains=tell_list(x.describe() for x in self.contents),
                             **self.__dict__)

    def priority(self):
        return [-4,1,10,5][self.healthparam]

class Player(Unit):
    def __init__(self, location, name):
        Unit.__init__(self, location, name)
        self.location.entities.remove(self)
        self.location = None
    def describe(self, spec_article=""):
        return "you"
    def free_action(self):
        if 0 < self.healthparam < 3 and not randrange(200):
            self.healthparam += 1


class Monster(Unit):
    def __init__(self, location, name, strength, health, loot=None):
        Unit.__init__(self, location, name)
        self.aggressive = True
        self.strength = strength
        self.healthnum = health
        self.loot = loot or []

class Shopkeeper(Unit):
    def buy(self,item):
        if Item("coin") in self.parent.player.contents and item in self.contents:
            self.parent.player.contents.remove(Item("coin"))
            self.contents.append(Item("coin"))
            self.parent.player.contents.append(item)
            self.contents.remove(item)
            self.send_format("Transaction completed")
        else:
            self.send_format("No coin availiable")
    def sell(self,item):
        if Item("coin") in self.contents and item in self.parent.player.contents:
            self.contents.remove(Item("coin"))
            self.parent.player.contents.append(Item("coin"))
            self.contents.append(item)
            self.parent.player.contents.remove(item)
            self.send_format("Transaction completed")
        else:
            self.send_format("No coin availiable")
class Item:
    def __init__(self, name):
        self.name = name

    def __eq__(self,other):
        isinstance(other,Item)
        self.name = other.name

    def describe(self, spec_article=""):
        if spec_article:
            article = spec_article
        elif self.name[0] in "aeiou":
            article = "an"
        else:
            article = "a"
        return "{} {}".format(article, self.name)


class Weapon(Item):
    def __init__(self, name, damage):
        Item.__init__(self, name)
        self.damage = damage



def generate_map_tiles(parent, size):
    tiles = {}
    for x, y in product(range(size), repeat=2):
        tiles[(x, y)] = MapTile(parent)
        tiles[(x, y)].name = choice(parent.data["tiles"])
    for x, y in product(range(size), repeat=2):
        tiles[(x, y)].border["north"] = tiles[(x, (y - 1) % size)]
        tiles[(x, y)].border["south"] = tiles[(x, (y + 1) % size)]
        tiles[(x, y)].border["west"] = tiles[((x - 1) % size, y)]
        tiles[(x, y)].border["east"] = tiles[((x + 1) % size, y)]
        generate_tree(tiles[(x, y)])
        generate_goblins(tiles[(x, y)])
        generate_shop(tiles[(x, y)])
    return choice(list(tiles.values()))


def generate_tree(maptile):
    fruit, name = choice(("apple|appletree", "pear|peartree", "acorn|oak")).split("|")
    tree = Lootable(maptile, name)
    fruit = Item(fruit)
    tree.contents.append(fruit)

def generate_goblins(location):
    if randrange(10):
        return
    for i in range(randrange(5)+1):
        name = "goblin|goblin thief|goblin raider|goblin medic|goblin caster".split("|")[i]
        Monster(location,name,4,20)

def generate_shop(location):
    if randrange(3):
        return
    shop = Building(location,"shop")
    keep = Shopkeeper(shop,"merchant")
    keep.contents = [Item("apple")]*5 + [Item("coin")]*5

if __name__ == "__main__":
    with Interface() as i:
        g = GameState(i)
        g.mainloop()
    print("done")
