## Adobe Experience Manager Dispatcher filter testing Docker image
This image is located in docker hub here:
<LINK GOES HERE>

This repo is the Dockerfile source and dependent files to make this work.
Instructions are here and in docker hub for convenience.

## What is this?
Adobe Experience Manager is an Adobe product that uses Apache Sling.  Apache Sling is powerful and weird.
With each deployment of AEM it's normally fronted with a different webserver that uses a module written specifically for AEM.  It's an intelligent proxy / cache / access control web tier.

Writing filters for the dispatcher can be challenging and there isn't an easy sandbox for people to sharpen their skills with.  This docker image stands up a fake backend renderer to act as AEM and an Apache Webserver that uses the dispatcher handler .so file and base configuration farm to make it work.

This way you can stand up a quick box to create a new filter rule for and get it to work and tear it down quickly.

## What is the point?
One challenge is writing good dispatcher filter rules from the documentation listed here:
https://docs.adobe.com/content/help/en/experience-manager-dispatcher/using/configuring/dispatcher-configuration.html#configuring-access-to-content-filter

## What do I need?
Because the dispatcher module is closed source I can't bake it into the image so you'll need to download the version you're wanting to use from here:
https://helpx.adobe.com/experience-manager/dispatcher/release-notes.html#Downloads

That way you agree to Adobe terms of use etc..
Download the version for apache 2.4 with ssl support for this image to work.
Extract the .tar.gz file and rename the .so file to dispatcher.so and drop it in the same directory as the Dockerfile

You'll then create a filters.any file with your filter rules you want to test.  This file will get mapped to your workstation so you can make changes and re-run your docker image and it will pick up the changes.
