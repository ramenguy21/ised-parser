Quick Start Guide

1. Prerequisites
   bash# Install required Python package
   pip install pyserial
2. Run the Script
   bashpython ised_handler.py
3. # What You'll See
   iSED ESR Analyzer Communication Handler
   Medical Laboratory Integration System
   ============================================================

=== Available Serial Ports ===

1.  COM3 - USB Serial Port
2.  COM4 - Arduino Uno
3.  COM5 - USB-to-Serial Adapter

Select port (1-3): 4. Select Your Port

Choose the number corresponding to your iSED analyzer's serial port
Press Enter

5. Wait for Data
   2025-06-13 10:30:15 - INFO - Connected to iSED analyzer on COM3
   2025-06-13 10:30:15 - INFO - Ready to receive data (iSED is master device)
   2025-06-13 10:30:15 - INFO - Listening for iSED transmissions... (Press Ctrl+C to exit)
   What Happens When iSED Sends Data
   Real-time Display:
   📡 ENQ received from iSED - starting data reception
   ✅ ACK sent - ready for data frames
   🔬 Analyzer: Alcor iSED v01.00A (ID: 01)
   👤 Patient: John Doe (ID: 12345)
   🧪 Order: Sample ABC123 (Position: 01, Test: ESR)
   ✅ ESR Result: 15 mm/h (Normal measurement: 15.0 mm/hr) [Instrument: 01]
   🏁 Transmission terminated (Code: N)
   💾 Session saved: 1 results processed
   📊 Files created: ised_session_20250613_103045.json, ised_summary_20250613_103045.json
   Output Files
1. Detailed Session File (ised_session_YYYYMMDD_HHMMSS.json)
   Contains complete raw data from the analyzer
1. Summary File (ised_summary_YYYYMMDD_HHMMSS.json)
   Human-readable summary with:

Session statistics
Patient information
Test results with interpretations

3. Log File (ised_log_YYYYMMDD.log)
   Complete communication log for debugging
   Common Scenarios
   Normal Operation:

Connect cable between PC and iSED analyzer
Run script and select correct port
Initiate test on iSED analyzer
Watch real-time data flow
Review saved files when complete

Troubleshooting:
bash# If no ports appear:

- Check USB/serial cable connection
- Verify iSED analyzer is powered on
- Check Windows Device Manager for port assignment

# If connection fails:

- Try different baud rate (though 9600 is standard)
- Check cable pinout (DB9 male connector)
- Verify XON/XOFF flow control settings
  Testing Without iSED:
  You can test the script structure by examining the code, but actual data flow requires the physical iSED analyzer since it's the master device that initiates all communication.
  Key Points for Your Presentation

The script is passive - it waits for the iSED to send data
Real-time feedback - you see exactly what's happening
Automatic file saving - no manual intervention needed
Error handling - shows checksum failures, retransmissions, etc.
Easy debugging - comprehensive logging for troubleshooting

Exit the Program
Press Ctrl+C at any time to safely shut down and close the serial connection.
The script handles multiple transmission sessions automatically - just leave it running and it will process each test as the iSED sends data.
