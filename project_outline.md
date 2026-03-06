<h1 style="text-align: center;">OpenSerialComms Project Outline</h1>

## Table of Contents
- [Table of Contents](#table-of-contents)
- [Outline Summary](#outline-summary)
- [Package Features](#package-features)
- [Project description](#project-description)
- [API](#api)
- [TUI](#tui)
  - [Command line](#command-line)
  - [Main Screen](#main-screen)
  - [Port Selection Screen](#port-selection-screen)
  - [Help Screen](#help-screen)
- [Documentaion](#documentaion)


## Outline Summary
Create a python package "OpenSerialComms", or "OSC" in this directory.

---

## Package Features
The package should set up for installation using pip and feature GNU open source license.

---

## Project description
OpenSerialComms should create an API and TUI interface for interacting with devices over a serial port.

---

## API
The API should function as the core of the project, creating all the functionality for using the TUI from the command line or use as a python import to stream or write/read messages dynamically or create further scripting. Using `pyserial`, create a `connect()` function with all the parameters needed to connect to the port. This should return a "SerialPort" class object with the port already opened, and feature three methods:
- `SerialPort.write(message="")`: Allows the user to write a message to the port. Either writes the message directly using pyserial, or adds it to a queue to be run.
- `SerialPort.stream()`: Creates a loop to continually stream messages to the standard output. Uses async or state machine in loop to check for additional messages from the queue to send the port or close the connection.
- `SerialPort.close()`: Closes all connections to the port and breaks any `.stream()` loops.

To continually stream messages:
```python
import openserialcomms as osc

port = osc.connect("COM5")
port.stream()
```

Critically, once a serial port is opened, this locks other instances from accessing it. To get around this, the program should open three sockets:
- A fixed socket that instances of the API can message to ask for what serial ports have been opened, and what sockets to use for reading and writing to them.
- A socket to stream all messages for a given serial port
- A socket to write messages to the API instance locking the port to have it run them.

This means that the "SerialPort" class will need to contain a list of serial ports currently open and the read/write socket information for each, a queue for any messages it is sent over socket for its port, and additional methods for asynchronously listening and writing on the sockets.

For example, assume we have four different python instances, all opened in order, and all attempting to connect to COM5.

Instance 1:
```python
import openserialcomms as osc

port = osc.connect("COM5")
port.stream()
```

Instance 2:
```python
import openserialcomms as osc

port = osc.connect("COM5")
port.stream()
```

Instance 3:
```python
import openserialcomms as osc

port = osc.connect("COM5")
port.write("Hello Vietnam")
```

Instance 4:
```python
import openserialcomms as osc

port = osc.connect("COM5")
port.close()
```

Because Instance 1 was first, it will not see any other instances when checking the designated socket for open ports (for example, 14563), and create the actual connection to COM5 using pyserial. It will then choose sockets to listen for messages to write (for example, 14564) and stream messages from the serial port to (for example, 14565), update the list of open ports with this info, and asynchronously begin listening to the designated socket (14563) and message queue socket (14564), and streaming messages form the port to the stream socket (14565).

When Instance 2 opens, it will check the designated socket (14563) for open ports, and Instance 1 will respond with a JSON message that COM5 is open with write socket 14564 and stream socket 14565. Instance 2 will update its list of open ports with this info. When `port.stream()` is called in the code, Instance 2 will connect to the stream socket 14565 and write it to the standard out.

When Instance 3 is created, it will repeat the same process of checking for open ports and updating its list. Only Instance 1, with an actual `pyserial` connection, will respond to the "what ports are open?" request on socket 14563. Because Instance 3 does not own the `pyserial` connection, when Instance 2 runs `port.write("Hello Vietnam")`, this will be sent over socket 14564. On Instance 1, the listener will recieve this and add it to the message queue. If Instance 1 were not already running the `.stream()` loop, the message would immediately sent to COM5 and cleared from the queue. Because `.stream()` is running, it will check the queue once per loop, write the message to COM5, clear it from the queue, and continue checking for messages from COM5 to write to the standard out.

Instance 4 repeats the same process of checking for open ports and updating its list. When `port.close()` is called, it send a special message to socket 14564. The message will be read by the Instance 1 listener and added to the message queue, but when the loop encounters it, it will close the `pyserial` connection and send a special message back out over the stream socket 14565. This special message will instruct anyone listening to COM5 that the connection is now closed. All instances will then clear their internal lists and queues and close all socket connections. 

---

## TUI

### Command line 
Using `argparse`, create a command line tool that is installed with the library. The tool should be added to the PATH or installed in the user's bin as part of the pip installation. It should have at least the following features:

- `-port <serial-port-to-connect-to>`: This argument allows the user to specify which serial port to connect to. If none is specified, the program will search for all available serial ports and open [a special TUI](#port-selection-screen) for selecting one. Must be a string.
- `-baud <baud-rate-to-use>`: Specify the baud rate. If none is specified, default to 115200. Can be string or integer.
- `-timeout <time-out>`: Timeout to use. Can be string or integer.
- `-help`: Displays information on how to use the command.

Example usage: 
```bash
osc -port "COM5" -baud "9600" -timeout 1
```

After running the command, the terminal should switch to the TUI interface using the paramters specified.

### Main Screen
Using `textual`, create a TUI to interact with the serial port. Split the screen into two blocks. The top block should take up most of the screen and display a stream of all the messages to the port. The bottom block should contain a space where commands can be entered and a banner at the bottom that should display the port currently connect on the left, and this small list of information on the right: ">msg port    help - list cmds". More info can be added to the banner as needed.

Main TUI wireframe:

    ┌────────────────────────────────────────────────────────────────────────────────┐
    │ Messages streamed here                                                         │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    ├─────────────────────────────────────────────┬──────────────────────────────────┤
    │                                             │                                  │
    │   Commands are written here                 │ Command output here              │
    │                                             │                                  │
    ├─────────────────────────────────────────────┴──────────────────────────────────┤
    │ Connected to: COM5                               >msg port    help - list cmds │
    └────────────────────────────────────────────────────────────────────────────────┘

The top block for message streaming should be scrollable and have a very long history. The messages streamed here should be saved in memory in case the user chooses to log them. Messages should start appearing from the top, with each new message added underneath the last one until the bottom of the block. After the block is filled, each new message should cause the previous one to appear to jump up one line. These older messages should then be able to be scrolled up to see again.

Commands for the TUI can be entered in the command block. Whenever a command is entered, it is then cleared from the screen. If the command has an output, it should be display in the output box. To write a message to the port, the user should be able to prefix the message with a `>`. These messages should then appear in the message streaming box, prefixed by a `> `, and in the color green to stand out as not being messages from the port.

    ┌────────────────────────────────────────────────────────────────────────────────┐
    │ Message sample 1                                                               │
    │ Message sample 2                                                               │
    │ Message sample 3                                                               │
    │ > User message to port (in green)                                              │
    │ Message sample 4                                                               │
    │ Message sample 5                                                               │
    │ Message sample 6                                                               │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    ├─────────────────────────────────────────────┬──────────────────────────────────┤
    │                                             │                                  │
    │   Commands are written here                 │ Command output here              │
    │                                             │                                  │
    ├─────────────────────────────────────────────┴──────────────────────────────────┤
    │ Connected to: COM5                               >msg port    help - list cmds │
    └────────────────────────────────────────────────────────────────────────────────┘

Command parsing will need to be handled in a simple, easy-to-find way that can easily be updated or extended with new commands. These commands will all follow a standard "bash-style" format, so using something like `argparse` to allow for defining what the commands and arguments are would be useful.

Commands list:
- `>`: Prefix indicating that the following is to be written to the port.
- `help`: Opens the help screen. All messages, including those missed while this screen is open, should still be displayed in message stream box when it is closed.
- `clear`: Clears the message stream display, but maintains the history in case logging is specified
- `close`: Closes the connection to the current port and clears the message stream display. If the port is already closed, retruns that no port is open.
- `exit`: Closes the connection to the current port and cleanly quits the program.
- `log <"path/to/file">`: Creates or opens the file specified, dumps the current log history, and continues to log new messages there until the connection is closed. When a connection is closed, the programs internal log history should be purged.
- `open <serial-port-to-connect-to>`: Opens a new connection to the port specified. If no port is specified, open the [port selection screen](#port-selection-screen). Should only work if the TUI is not currently connected to a port; if it is, using this command should return a message "Please close the current connection".
- `run <"path/to/file">`: Allows the user to specify a file to load and write the contents to the open port.

### Port Selection Screen
If no port is provided during the initial `osc` command to launch the TUI, a screen should be displayed showing the available serial ports to connect to. Using the up and down arrows should allow the user to cycle through the options. The currently selected option should appear in green, possibly with a `>` in front of it, depending on what most `textual` applications use for these kinds of screens. Hitting enter on the selected port should then move the user to the main TUI screen using this serial port and the defaults for any other unspecified settings. The bottom of the screen should feature a banner with "OpenSerialComms 2026" or "OpenSerialComms" and the current version in the left.

Port select wireframe:

    ┌────────────────────────────────────────────────────────────────────────────────┐
    │                                                                                │
    │                       Select a serial port to connect to:                      │
    │                                                                                │
    │    [COM 3]                                                                     │
    │                                                                                │
    │   >[COM 4]                                                                     │
    │                                                                                │
    │    [COM 5]                                                                     │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    │                                                                                │
    ├────────────────────────────────────────────────────────────────────────────────┤
    │ OpenSerialComms 2026                                                           │
    └────────────────────────────────────────────────────────────────────────────────┘

### Help Screen
The help screen should display a list of commands and information on what each one does and how to use it. It should be possible to "scroll" through the commands using the up and down arrow keys. The currently selected command should be highlighted with a box of a different color to the background. The left and right arrow keys should cycle between the [select command] and [return] buttons at the bottom of the screen. Hitting enter on any command with the [select command] button selected should drop the user back to the [main screen](#main-screen) and insert a sample of that command into the command prompt there. Hitting enter on any command with the [return] button selected should return the user to main screen with the prompt cleared.

Help screen wireframe:

    ┌────────────────────────────────────────────────────────────────────────────────┐
    │                                                                                │
    │                                 OSC Commands                                   │
    │                                                                                │
    │    help                                                                        │
    │        Displays this screen with osc commands.                                 │
    │                                                                                │
    │    >                                                                           │
    │        Prefix used to write a message to the selected port, i.e.:              │
    │        >my-message-here                                                        │
    │                                                                                │
    │    close                                                                       │
    │        Closes the connection to the current port.                              │
    │                                                                                │
    │    exit                                                                        │
    │        Closes the connection to the current port and quits the program.        │
    │                                                                                │
    │    log "path/to/file"                                                          │
    │        Creates or opens the file specified, dumps the current log history,     │
    │        and continues to log new messages there until the connection is         │
    ├────────────────────────────────────────────────────────────────────────────────┤
    │ Connected to: COM5                               >[select command]    [return] │
    └────────────────────────────────────────────────────────────────────────────────┘

---

## Documentaion
Create a README.md file and any other documention needed to explain the installation, function, and use of the package.