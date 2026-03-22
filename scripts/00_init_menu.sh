#!/bin/bash

/emulator/hd_menu &
sleep 5
kill -9 `pidof hd_menu`

