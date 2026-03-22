# Navigation Menu

## Companion


### Settings

**OnesaUCE Target Folder**
OnesaUCE can be installed one of the following ways
-  To a folder on a hard drive in your PC for backups or browsing media
-  To a blank NTFS formatted USB drive to use on your AtGames Legends device
-  To your existing OnesaUCE 2.0 USB drive, for performing updates or adding additional components

Note:   OnesaUCE 1.x based drives are not supported.   There is no clean upgrade path from 1.x to 2.0, so your best option is to wipe and reinstall, or use a different drive if you want to keep your original 1.x

**BitLCD Target Folder**

The BitLCD is a separate accessory for the AtGames Legends Ultimate series of products allowing the user to display marquee images based on what game is currently selected in OnesaUCE.    It uses a removable flash drive for the storage of BitLCD marquee images.    You can use OnesaUCE Companion to manage the image sets installed to the drive.

BitLCD Marquee components can be installed one of the following ways
-  To a folder on a hard drive in your PC for backups or browsing marquee art.
-  To a blank FAT32 formatted USB drive, for use in your BitLCD device.
-  To an existing BitLCD USB drive for adding or updating Marquee packs.

Note:   For marquees to be seen by the BitLCD device, they need to be installed somewhere within the bitlcd/thirdparty folder.   It's recommended to create a bitlcd/thirdparty/onesauce folder and use that as your target folder.    Each marquee pack will install to it's own subfolder within the target folder.   

The OnesaUCE and BitLCD Target Folders must reside on, or be plugged into your PC.    Installing to network drives has not been tested.    Companion does not connect remotely to any AtGames legends devices.

**Archive.org Credentials**

OnesauCE downloads are hosted by the Internet Archive.    Because these are larger downloads, it does require users to be authenticated in order to access the downloads.     You can specify your email and password and specify a max number of parallel downloads.

**Downloads**

All downloads are installed to the location specified by your Target Folder and/or BitLCD Folder.    Companion needs to download the files before they are installed, so this section is where you will specify a downloads folder.   It's not recommended that you use your OnesaUCE drive for this storage, but it is possible.

You can also specify a retention policy for your downloads.    Your options are:

* Keep the latest version of each downloaded component
* Delete after every install (for minimal space usage)
* Keep zips up to a number of days
* Keep zips up to a max amount of space in GB


## Queue

The Queue allows you to manage the downloads of multiple components.    Each component in the queue will be listed along with the status of the download/install.    You can reorder items in the Queue to increase their relative priority in the download order.

Note that although you can download multiple components at once, only one gets installed at a time, so you will see this as a likely bottleneck when downloading many components at once.

The Queue can be paused and restarted as needed.     The Queue is preserved when exiting Companion.

![Queue](docs/Queue.png)

## Install

### Base Components

The Base Components screen displays core OnesaUCE components.    These are all required in order to have a functional OnesaUCE installation.    

OnesaUCE Companion tracks which versions of components you have installed, and will check if newer versions are available.     If a component is missing or has an available update, then you can select that component to be added to the Queue for download and installation.

![Base Components](docs/BaseComponents.png)

### System Packs

The System screen displays System Packs for computers, consoles, handhelds, and other systems supported by OnesaUCE.    

![System Packs](docs/SystemPacks.png)

### BitLCD Marquees

The BitLCD screen displays marquee packs for various systems supported by OnesaUCE.

![BitLCD Marquees](docs/BitLCDMarquees.png)

### Optional Components

The Optional Component screen includes optional components including Themes, Attract Videos, and Jukebox videos.

![Optional Components](docs/OptionalComponents.png)

## OnesaUCE

### Games

Browse indexed games from installed content, filter and sort the catalog, and inspect media/details for a specific title.

![Games](docs/Games.png)

![Game Details](docs/GameDetails.png)

### Collections

Browse the set of available collections, filter and sort the catalog, and inspect media/details for a specific collection.

![Collections](docs/Collections.png)

![CollectionDetails](docs/CollectionDetails.png)

###  Logs

View the log file from Companion along with other log files from OnesaUCE.    Includes syntax highlighting and configurable colors.

![Logs](docs/Logs.png)

![Color Config](docs/LogColors.png)

### Settings

**Autostart Status**

OnesaUCE can be configured to autostart when turning on your AtGames Legends Device.    The current status of this setting will be displayed, with the ability to enable or disable the setting.

Some AtGames Legends devices will freeze when the autostart setting is enabled.    In those cases, a separate fix can be installed, but should only be installed if needed.

**Settings Tweaks**

Setting to enable the screen rotation fix, specific to the AtGames Legends Pinball Micro.    This should not be applied for other AtGames devices.

**OnesaUCE Settings**

Other OnesaUCE related settings can be changed here.

![OnesaUCE Settings](docs/OnesaUCESettings.png)