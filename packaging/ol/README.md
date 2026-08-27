# ol

This distribution contains **no code**. It exists so that the name you install matches
the command you type.

```bash
pip install ol
```

That installs [`openloops`](https://pypi.org/project/openloops/), and `openloops` is what
puts the `ol` command on your PATH. `pip install openloops` does exactly the same thing.
Same command, same package, two spellings of the install line — pick whichever one you
remember.

**The real project is [thorwhalen/openloops](https://github.com/thorwhalen/openloops).**
Documentation, issues, changelog and every line of source live there. Nothing is
maintained here.

## What you get

An **open loop** is a commitment that outlived the session that made it and that nothing
is watching. `openloops` finds those and re-checks them, and never writes anything back:

| You want to know | Run |
|---|---|
| What did my sessions leave open? | `ol` |
| What do I still owe my agents? | `ol owed` |
| What is waiting on another repo, and what is not any more? | `ol blocked` |

`ol owed` and `ol blocked` report three states, and the third is `unknown`, rendered `?`.
It is never quietly folded into "fine" — a surface that reports a clean answer because it
failed to check is worse than no surface.

## Versions

The version of `ol` is its own and says nothing about the version of `openloops` you get.
`ol 0.1.0` does not mean `openloops 0.1.0`; run `pip show openloops` for that.

`ol` depends on `openloops` with a floor (`>=`), not a pin. So `pip install ol` always
resolves the newest `openloops`, and this alias does not need re-releasing every time the
real package ships. It is registered once and then it is finished.

## Names that are not this one

The `ol` on your PATH is only ours if you put it there. One other tool installs an
executable by that name: **Otus Lisp**, a purely functional Lisp dialect, whose Homebrew
formula is also called `ol` and which installs `ol` and `olvm`. It is a genuine PATH
collision rather than a theoretical one, though a quiet one — 24 Homebrew installs in the
last year, against no overlap in audience. If you run both, whichever comes first on your
PATH wins, and `which -a ol` will tell you which that is.

Two more names to know about, neither of which puts an `ol` on your PATH:

- **`ol` on npm** is [OpenLayers](https://www.npmjs.com/package/ol), the mapping library.
  It ships no executable, so it cannot collide — but it will dominate a web search.
- **OpenLoops** is an established particle-physics one-loop amplitude library
  ([openloops.hepforge.org](https://openloops.hepforge.org)), and **openloops** is also
  [a browser-history tool](https://github.com/sholajegede/openloops). Neither is on PyPI.
  The parent README says more about both.

All of this was checked, not assumed. Registering the short name was the cheap half of
that; saying plainly what it does and does not point at is the half that matters.

## License

Apache-2.0, the same as the package it installs. The license text ships with `openloops`,
which is where the licensed work actually is.
