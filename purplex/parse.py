import collections
import functools
import itertools
import logging

from purplex.grammar import Grammar, Production, END_OF_INPUT
from purplex.lex import Lexer
from purplex.token import Token

END_OF_INPUT_TOKEN = Token(END_OF_INPUT, '', '', 0, 0)


def attach(rule):
    def wrapper(func):
        if not hasattr(func, 'productions'):
            func.productions = set()
        func.productions.add(Production(rule, func))
        return func
    return wrapper


def attach_list(nonterminal, singular, single=True, epsilon=False):
    def wrapper(func):
        productions = [
            '{} : {} {}'.format(nonterminal, nonterminal, singular),
        ]
        if single:
            productions.append('{} : {}'.format(nonterminal, singular))
        if epsilon:
            productions.append('{} : '.format(nonterminal))

        for production in productions:
            attach(production)(func)
        return func
    return wrapper


def attach_sep_list(nonterminal, singular, separator, epsilon=False):
    def wrapper(func):
        inner_nonterminal = '{}_inner'.format(nonterminal)
        productions = [
            '{} : {}'.format(nonterminal, inner_nonterminal),
            '{} : {} {} {}'.format(inner_nonterminal, inner_nonterminal,
                                   separator, singular),
            '{} : {}'.format(inner_nonterminal, singular),
            ]
        if epsilon:
            productions.append('{} : '.format(nonterminal))

        for producution in productions:
            attach(producution)(func)
        return func
    return wrapper


class ParserBase(type):

    def __new__(cls, name, bases, dct):
        productions = set()
        for _, attr in dct.items():
            if hasattr(attr, 'productions'):
                productions |= attr.productions

        grammar = Grammar(
            dct['LEXER'].tokens.keys(),
            productions,
            start=dct['START'],
        )
        INITIAL_STATE, ACTION, GOTO = cls.make_tables(grammar)
        dct.update({
            'grammar': grammar,
            'INITIAL_STATE': INITIAL_STATE,
            'ACTION': ACTION,
            'GOTO': GOTO,
        })
        return type.__new__(cls, name, bases, dct)

    @staticmethod
    def make_tables(grammar):
        """Generates the ACTION and GOTO tables for the grammar.

        Returns:
            action - dict[state][lookahead] = (action, ...)
            goto - dict[state][just_reduced] = new_state

        """
        ACTION = collections.defaultdict(dict)
        GOTO = collections.defaultdict(dict)

        labels = {}

        def get_label(closure):
            if closure not in labels:
                labels[closure] = len(labels)
            return labels[closure]

        initial, closures, goto = grammar.closures()
        for closure in closures:
            label = get_label(closure)

            for rule in closure:
                if not rule.at_end:
                    symbol = rule.rhs[rule.pos]
                    is_terminal = symbol in grammar.terminals
                    has_goto = symbol in goto[closure]
                    if is_terminal and has_goto:
                        ACTION[label][symbol] = \
                            ('shift', get_label(goto[closure][symbol]))
                elif rule.production == grammar.start and rule.at_end:
                    ACTION[label][rule.lookahead] = ('accept',)
                elif rule.at_end:
                    ACTION[label][rule.lookahead] = \
                        ('reduce', rule.production)

            for symbol in grammar.nonterminals:
                if symbol in goto[closure]:
                    GOTO[label][symbol] = get_label(goto[closure][symbol])

        return get_label(initial), ACTION, GOTO


class Parser(metaclass=ParserBase):

    LEXER = Lexer
    START = 'S'

    grammar = None
    INITIAL_STATE = 0
    ACTION = {}
    GOTO = {}

    def parse(self, raw):
        """Parses an input string and applies the parser's grammar."""
        lexer = self.LEXER(raw)
        tokens = iter(itertools.chain(lexer, [END_OF_INPUT_TOKEN]))
        stack = [(self.INITIAL_STATE, '<initial>', '<begin>')]

        token = next(tokens)
        while stack:
            state, _, _ = stack[-1]
            action = self.ACTION[state][token.name]

            if action[0] == 'reduce':
                production = action[1]

                # Special case for epsilon rules
                if len(production):
                    args = (item[2] for item in stack[-len(production):])
                    del stack[-len(production):]
                else:
                    args = []

                prev_state, _, _ = stack[-1]
                new_state = self.GOTO[prev_state][production.lhs]
                stack.append((
                    new_state,
                    production.lhs,
                    production.func(self, *args),
                ))
            elif action[0] == 'shift':
                stack.append((action[1], token.name, token.value))
                token = next(tokens)
            elif action[0] == 'accept':
                if len(stack) == 2:
                    return stack[-1][2]
                else:
                    # XXX: Raise something more meaningful
                    raise Exception('unparsed input remaining')

        # XXX: Raise something more meaningful
        raise Exception('ran out of input')
