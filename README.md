# Adobe Experience Manager Dispatcher filter testing Docker image
This image is located in docker hub here:
https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing

This repo is the Dockerfile source and dependent files to make this work.
Instructions are here and in docker hub for convenience.

# What is this?
Adobe Experience Manager is an Adobe product that uses Apache Sling.  Apache Sling is powerful and weird.
With each deployment of AEM it's normally fronted with a different webserver that uses a module written specifically for AEM.  It's an intelligent proxy / cache / access control web tier.

Writing filters for the dispatcher can be challenging and there isn't an easy sandbox for people to sharpen their skills with.  This docker image stands up a fake backend renderer to act as AEM and an Apache Webserver that uses the dispatcher handler .so file and base configuration farm to make it work.

This way you can stand up a quick box to create a new filter rule for and get it to work and tear it down quickly.

# What is the point?
One challenge is writing good dispatcher filter rules from the documentation listed here:
https://docs.adobe.com/content/help/en/experience-manager-dispatcher/using/configuring/dispatcher-configuration.html#configuring-access-to-content-filter

# Demo

![Starting Container](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/master/dispatcher-filter-testing-compose.gif)

![Browser Testing Filters](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/master/dispatcher-filter-testing-examples.gif)

# What do I need?

## Docker

Create an account on [hub.docker.com](https://hub.docker.com/signup) you'll need it for pulling down public docker images.

Use your favorite installation to get Docker running on your machine.

The easiest option is `Docker Desktop` and you can get the installation media from [here](https://www.docker.com/products/docker-desktop/)

Run through the standard installation wizard and login to the client with your docker account.

## Clone this repo

```
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

## Create your own filter files

Then create any filters files you want with a .any extension with your filter rules you want to test.
Drop those files in the filters directory.
This file will get mapped to your workstation so you can make changes and re-run your docker image and it will pick up the changes.

## Get and run the container

There are different methods to use, docker run or docker-compose

### docker-compose (Easier)

```
docker-compose up
```

### docker pull or build

You can pull the published image from [hub.docker.com](https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing):

```
docker pull pryor/aem-dispatcher-filter-testing:rockylinux8
```

Or if you want you can also build it yourself from the source in this repo so you can trust there isn't anything snuck in on the prebuild image.

Use this method if you want to make any alterations to the image as well.

```
docker build -t pryor/aem-dispatcher-filter-testing:rockylinux8 .
```

#### docker run

```
docker run -p 80:80 -v /DIR_YOU_CLONED_TO/filters/:/etc/httpd/conf.dispatcher.d/filters/ -v /DIR_YOU_CLONED_TO/logs/:/var/log/httpd/ pryor/aem-dispatcher-filter-testing:rockylinux8
```

Now you can tail the log files

```
tail -f logs/filter-test.log
```

As you visit your browser you'll see the relevant log entries for allows and denies for the filters