# Changelog

## [v2019.7] 
### Added
- gain_factor field on video device for scaling the gain under special circumstances

### Changed
- Updated ISARA interface
- Now using new ImageIO module based on OpenCV.
- microscope controller now uses gain_factor to change the gain during alignment mode instead 
  of setting the gain directly
- Camera zoom slave now works properly when camera implements a gain property changed through
  configure. Gain is calculated from the zoom position dynamically.