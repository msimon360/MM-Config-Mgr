# MM-Config-Mgr
A menu driven shell script to test new modules and update your config file for Magic Mirror.

It runs from a set of template files you can add to and update as you choose.
If you are using the pages module it will allow you to add and remove modules from your pages
and create new pages.

When you choose Add new module you are given the option to change the position value.

Here are the steps it follows. At each step you choose to continue or revert to you original
config.js file.

1. Test module in minimal config (without pages)
1. Test module with simple pages config (clock on page 1, your module on page 2)
1. Add module to master config
1. Make this the new master
