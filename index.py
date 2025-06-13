import serial

ser = serial.Serial(port='COM1', baudrate=9600, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, 
                    stopbits=serial.STOPBITS_ONE, timeout=10, xonxoff=True)


# control characters 
ENQ = b'\x05'     # ENQ - Enquiry
ACK = b'\x06'     # ACK - Acknowledge
NAK = b'\x15'     # NAK - Negative Acknowledge
STX = b'\x02'     # STX - Start of Text
ETX = b'\x03'     # ETX - End of Text
EOT = b'\x04'     # EOT - End of Transmission
CR = b'\x0D'      # Carriage Return
LF = b'\x0A'      # Line Feed
XON = b'\x11'     # XON - Resume transmission
XOFF = b'\x13'    # XOFF - Pause transmission

def process_ised_data():
    while True:
        # Wait for ENQ 
        data = ser.read(1)
        
        if data == ENQ:
            # Acknowledge the ENQ
            ser.write(ACK)
            
            # Wait for data frames
            while True:
                frame = ser.read_until(ETX)  # Read until ETX
                if not frame:
                    break  # Timeout occurred
                
                if frame.startswith(STX):
                    # Verify checksum
                    if verify_checksum(frame):
                        ser.write(ACK)
                        process_frame(frame)
                    else:
                        ser.write(NAK)
                elif frame.startswith(EOT):
                    ser.write(ACK)
                    break

# Sum of ASCII values from <STX> (excluded) to <ETX> (included), modulo 256.
def verify_checksum(frame):
    # Extract the checksum from the frame (last 2 bytes before CRLF)
    received_checksum = frame[-4:-2].decode('ascii')
    
    # Calculate checksum from STX to ETX (excluding STX, including ETX)
    data_part = frame[1:frame.find(ETX)+1]
    calculated_sum = sum(ord(c) for c in data_part) % 256
    calculated_checksum = f"{calculated_sum:02X}"
    
    return received_checksum == calculated_checksum

def process_frame(frame):
    # Extract frame number (second byte)
    frame_number = frame[1:2].decode('ascii')
    
    # Extract data message (between STX+number and ETX)
    data_message = frame[2:frame.find(ETX)].decode('ascii')
    
    # Split into records (separated by CR)
    records = data_message.split(CR.decode('ascii'))
    
    for record in records:
        if not record:
            continue
            
        record_type = record[0]
        
        if record_type == 'H':
            process_header_record(record)
        elif record_type == 'P':
            process_patient_record(record)
        elif record_type == 'O':
            process_order_record(record)
        elif record_type == 'R':
            process_result_record(record)
        elif record_type == 'L':
            process_terminator_record(record)
    
def process_header_record(record):
    pass

def process_patient_record(record):
    pass

def process_order_record(record):
    pass

def process_result_record(record):
    pass

def process_terminator_record(record):
    pass