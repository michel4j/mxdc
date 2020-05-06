Changelog
=========

v2020.5
-------
- Ported code to Python 3
- Simplified and unified Device, Service and Engine interfaces
- Refactored Goniometer and Sample Stage modules to be more integrated.
- Multiple improvements to beamline console and Simulator
- Separate configuration from main repository. Added an example configuration to "deploy"
- Rewrote run wedge calculations to be more consistent 
- Re-enable support for inverse-beam mode which was broken in previous releases
- Beam Tuner panel moved to Samples view.
- Rastering panel moved to Data view
- Chat panel moved to its own view together with the log viewer.
- Custom avatar support added to chat
- GUI tuned to fit within a smaller footprint to allow for use on smaller screens
- Added dark mode capability switchable from the application header-bar menu.


v2019.7
-------

- gain_factor field on video device for scaling the gain under special circumstances
- Updated ISARA interface
- Now using new ImageIO module based on OpenCV.
- microscope controller now uses gain_factor to change the gain during alignment mode instead 
  of setting the gain directly
- Camera zoom slave now works properly when camera implements a gain property changed through
  configure. Gain is calculated from the zoom position dynamically.