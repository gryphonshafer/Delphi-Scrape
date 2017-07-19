# Delphi Forum Scrape

This is a fairly simple application that runs from within a
[Docker](https://www.docker.com) container to scrape content from a
[Delphi forums](http://delphiforums.com) and store it in a common data storage
format ([YAML](https://en.wikipedia.org/wiki/YAML)). It also pulls (when able)
copies of embedded images and attachments.

The application is released under the [MIT License](LICENSE).

## Setup

The application runs from within a [Docker](https://www.docker.com) container,
so prior to setup you'll need to ensure you have
[Docker](https://www.docker.com) installed and configured properly. This should
be the only prerequisite.

The first step of the setup process is to build a
[Docker](https://www.docker.com) image based on the [Dockerfile](Dockerfile)
from this project:

    cd Delphi-Scrape # or whatever directory you placed this application's files within
    sudo docker build --compress --tag phantomjs .

Next, create and start a container based on the image, using the `/app`
directory inside it synchronized to your local current directory (which should
be the application's root directory):

    sudo docker run --rm -i -t -v `pwd`:/app --name phantomjs --hostname phantomjs phantomjs

## Initial Execution

To get details about application execution, run the following command:

    ./scrape --help

You'll need to know the forum code name of the forum you'd like to scrape.
(You'll also need a valid username and password to access that forum.) A typical
forum might have a base URL that looks like this:

    http://forums.delphiforums.com/FORUMNAME

A typical first-time run of the application might look like this:

    ./scrape -f FORUMNAME -u USERNAME -p PASSWORD

You can safely rerun this command if for whatever reason the application stops
mid-execution. The application will look at its storage of data and skip what it
has already pulled.

## Refreshing Data

After a successful full initial execution, you can rerun the application in
"refresh" mode to pull updated data from existing discussion threads. Rerun the
command, but append a refresh range.

    ./scrape -f FORUMNAME -u USERNAME -p PASSWORD -r RANGE

This refresh range is a number of days. If defined as a positive integer, the
program will do a refresh of threads with posts more recent that those number of
days. If you set refresh to "a" or "auto" or so on, then the number of days will
be calculated from the most recent last modified date of saved thread YAML data
files.
