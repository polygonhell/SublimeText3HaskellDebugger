# SublimeText3HaskellDebugger
This is just a proof of concept to understand what's required to embed a debugger in Sublime Text3.
Basicallly it just starts a "ghc --interactive" process and sends it commands via stdin, this is not a great way for a debugger to work, since the protocol is at best fragile. But it's enough to understand the limitations of a debugger hosted in sublime.
The current implementation is far from complete and has many limitations
It only deals with a single module path
It assumes that ghc is in /usr/local/bin/ghc
Column offsets are incorrect for none ASCII source files, the issue is that sublime works in characters and it appears ghc reports column offsets in bytes.

to use it you open the haskell source file with main in sublime, and select debug from the additional menu
Shift-Command-C will step through the code.
Not tested on anything but OSX.
