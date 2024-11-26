# "Cat printer" stock ticker (c) 2024 J. Bogin,  http://boginjr.com
# Uses NaitLee Cat-Printer core and the XTB xAPI wrapper
# Licensed under GPLv3-or-later

try:
    import bleak, PIL, tzdata
except:
    print("To run, install the following packages: bleak, pillow, tzdata:\npip install bleak\npip install pillow\npip install tzdata")
    quit()

from xtb.xAPIConnector import APIClient    
from printer_lib.printer import PrinterDriver
from msvcrt import getch, kbhit
from PIL import Image, ImageDraw, ImageFont
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import time
import io
import warnings
import getpass

# connection config
DEFAULT_USERID              = 0                                                   # numeric; if 0, to be prompted
DEFAULT_PASSWORD            = ""                                                  # if empty string, to be prompted
DEFAULT_ACCOUNT_TYPE        = ""                                                  # "REAL" or "DEMO", if empty string, to be prompted
DEFAULT_PING_FREQ_MINUTES   = 10                                                  # API recommends 1 ping every 10 minutes
DEFAULT_SYMBOLS             = ["SXR8.DE", "SXRV.DE", "XDWT.DE",                   # ETF
                               "MSFT.US_9", "AAPL.US_9", "IBM.US_9", "META.US_9", # stocks (_4 would be stocks CFD)
                               "EURUSD", "EURCHF",                                # forex CFD
                               "BITCOIN", "ETHEREUM",                             # crypto CFD
                               "GOLD", "OIL", "NATGAS"]                           # commodity CFD

# printing config
DEFAULT_PRINTER_NAME        = ""                                                  # Bluetooth printer name, if empty string, to be prompted
DEFAULT_PRINT_FREQ_MINUTES  = 15                                                  # how often to fetch data and print
DEFAULT_PRINT_FONT          = "C:\\Windows\\Fonts\\lucon.ttf"                     # must be truetype monospace or columns won't align right
DEFAULT_PRINT_EXTRA_FEED    = 0                                                   # extra feed in px, in addition to that in CatPrinterCore. 0: off

class XTBRetriever:
    def __init__(self):
        self._port = 5112 if (DEFAULT_ACCOUNT_TYPE == "REAL") else 5124        
        self._client = APIClient(port=self._port)
        self._result = self._client.commandExecute("login", dict(userId=DEFAULT_USERID, password=DEFAULT_PASSWORD, appName="CatPrinterStockTicker"))                                                          
        self._loggedIn = self._result["status"] == True

    def isLoggedIn(self):
        return self._loggedIn        
    
    def disconnect(self):
        try:
            self._client.disconnect()
        finally:
            return
        
    def getData(self, command, arguments=dict()):
        try:
            self._result = self._client.commandExecute(command, arguments)
            if (self._result["status"] == True):
                return self._result["returnData"]
            else:
                return dict(invalid="invalid")
        except:
            return dict(invalid="invalid")
            
    def dumpAllSymbols(self):
        self._file = open("all_symbols.txt", "w")
        print("Getting all symbols...")
        self._file.write(str(self.getData("getAllSymbols")))
        self._file.close()
        self.disconnect()
        print("Done")
        quit()
        
    def ping(self):
        try:
            self._result = self._client.commandExecute("ping")
            return self._result["status"] == True
        except:
            return False
            
    def dailyChange(self, symbol, currentPrice):        
        # look at the two last D1 candles (-5 ticks should get at least two day candles)
        self._data = self.getData("getChartRangeRequest", dict(info=dict(symbol=symbol, ticks=-5, period=24*60, start=round(time.time()*1000))))
        if (("invalid" not in self._data) and ("digits" in self._data) and ("rateInfos" in self._data) and (len(self._data["rateInfos"]) > 1)):                        
            self._idxLastDayCandle = len(self._data["rateInfos"]) - 1
            self._idxPenultimateDayCandle = self._idxLastDayCandle - 1
            
            # check if the market is/was open today (the last day candle is from today). warning, server "ctm" is in CET/CEST!
            self._lastDayCandle = datetime.fromtimestamp(self._data["rateInfos"][self._idxLastDayCandle]["ctm"] / 1000, tz=ZoneInfo("Europe/Warsaw"))
            if (datetime.now().day != self._lastDayCandle.day):
                return 0.0
                
            # compute daily change from the current price against the closing price of the penultimate day candle
            self._closingPrice = (self._data["rateInfos"][self._idxPenultimateDayCandle]["open"] +\
                                  self._data["rateInfos"][self._idxPenultimateDayCandle]["close"]) / 10**self._data["digits"]            
            if (self._closingPrice > 0):
                return round((currentPrice-self._closingPrice)/self._closingPrice*100, 2)
        return 0.0

def sprintf(*args, **kwargs):
    output = io.StringIO()
    print(*args, file=output, **kwargs)
    contents = output.getvalue()
    output.close()
    return contents        
            
def main():         
    print("\nConnecting to broker...");
    try:
        broker = XTBRetriever()
    except:        
        print("Cannot connect to server, quitting")
        return        
    if (broker.isLoggedIn() == False):
        print("Invalid login credentials, quitting")        
        return
               
    # uncomment the following to just dump all the available symbols (tickers) to file and quit
    #broker.dumpAllSymbols()
    
    retries = 3
    printer = PrinterDriver()
    warnings.filterwarnings("ignore")
    print("Connecting to printer " + DEFAULT_PRINTER_NAME + " via Bluetooth...")    
    while True:    
        try:
            found = False
            devices = printer.scan(everything=True)
            for device in devices:
                if device.name == DEFAULT_PRINTER_NAME:
                    printer.connect(device.name, device.address)
                    found = True
                    break
            if (not found):
                printer.unload()
            else:
                break
        finally:
            retries -= 1
            if (retries == 0):
                broker.disconnect()
                print("Printer " + DEFAULT_PRINTER_NAME + " not found, quitting")
                return
    
    # trigger print now, ping waits DEFAULT_PING_FREQ_MINUTES
    print("\nConnected; stock ticker each", DEFAULT_PRINT_FREQ_MINUTES, "minute(s).\n")
    pingTime = time.time()
    printTime = DEFAULT_PRINT_FREQ_MINUTES * 60
           
    while True:
           
        # ESC hit and retrieved from buffer, disconnect and quit
        if ((kbhit() != 0) and (ord(getch()) == 27)):
            break
        
        # ping every DEFAULT_PING_FREQ_MINUTES 
        if (time.time() - pingTime >= DEFAULT_PING_FREQ_MINUTES * 60):
            pingTime = time.time()
            print("\rPinging server...     \r", end="")
            if (not broker.ping()):
                printer.unload()
                print("\nPing unsuccessful, quitting")                
                return
            print("\rWaiting... (ESC quits)\r", end="")            
            
        # retrieve stocks every DEFAULT_PRINT_FREQ_MINUTES
        if (time.time() - printTime >= DEFAULT_PRINT_FREQ_MINUTES * 60):
            printTime = time.time()
            print("\rRetrieving data...    \r", end="")            
            
            tickPrices = broker.getData("getTickPrices", dict(symbols=DEFAULT_SYMBOLS, level=0, timestamp=0))
            if (("invalid" not in tickPrices) and ("quotations" in tickPrices) and (len(tickPrices["quotations"]) > 0)):                            
                
                # form text results
                stonks = ""
                
                timeStamp = datetime.fromtimestamp(broker.getData("getServerTime")["time"] / 1000)
                header = sprintf("XTB quotes as of %s (print-out every %d min.):" %\
                                (timeStamp.strftime("%d-%b-%Y %H:%M:%S"), DEFAULT_PRINT_FREQ_MINUTES))
                          
                totalProfits = 0.0
                account = broker.getData("getMarginLevel")
                profits = broker.getData("getTrades", dict(openedOnly=True))
                for profit in profits:
                    totalProfits += profit["profit"]
                
                footer = sprintf("%s acc value: %10.2f%s  profits: %+10.2f%s  unused: %10.2f%s" %\
                                 (DEFAULT_ACCOUNT_TYPE,\
                                 account["equity"], account["currency"],\
                                 totalProfits, account["currency"],
                                 account["margin_free"], account["currency"]))                                 
                
                for idx, symbol in enumerate(DEFAULT_SYMBOLS):                    
                    bid = tickPrices["quotations"][idx]["bid"]
                    ask = tickPrices["quotations"][idx]["ask"]
                    spread = tickPrices["quotations"][idx]["spreadTable"]                                       
                    tickSymbols = broker.getData("getSymbol", dict(symbol=symbol))                                     
                    dailyChange = broker.dailyChange(symbol, bid) 
                    categoryCurrency = "(" + tickSymbols["categoryName"] + ", " + tickSymbols["currency"] + ")"
                    stonks += sprintf("%12s %10s: ASK:%9.2f BID:%9.2f [ 1D: %+06.2f%% ] SPRD: %g" %\
                                     (symbol, categoryCurrency, ask, bid, dailyChange, spread))

                # create monochrome image from text for the cat printer, then rotate it (width must be 384px)
                big_font = ImageFont.truetype(DEFAULT_PRINT_FONT, 19)
                font = ImageFont.truetype(DEFAULT_PRINT_FONT, 17)                
                canvas = Image.new("1", (850,384), 1)
                draw = ImageDraw.Draw(canvas)
                draw.line([(0, 0), (850, 0)], fill=0, width=1)
                draw.line([(0, 383), (850, 383)], fill=0, width=1)
                draw.text((67, 5), header, fill=0, font=big_font)
                draw.multiline_text((4, 39), stonks, fill=0, font=font, spacing=8)
                draw.text((6, 360), footer, fill=0, font=big_font)
                buffer = io.BytesIO()
                canvas.rotate(90, expand=True).save(buffer, "PPM")
                buffer.seek(0)
             
                # print with slower speed (the lower the quicker); do extra feed if enabled
                print("\rSending to printer... \r", end="")
                try:
                    printer.energy = 0xffff
                    printer.speed = 64
                    printer.print(buffer)
                    
                    if (DEFAULT_PRINT_EXTRA_FEED > 0):
                        buffer = io.BytesIO()
                        canvas = Image.new("1", (384,DEFAULT_PRINT_EXTRA_FEED), 1).save(buffer, "PPM")
                        buffer.seek(0)
                        printer.energy = 0x4000
                        printer.speed = 8
                        printer.print(buffer)
                except:                    
                    broker.disconnect()
                    printer.unload()
                    print("\nFailed to communicate with " + DEFAULT_PRINTER_NAME + " printer, quitting")
                    return

            else:                
                broker.disconnect()
                printer.unload()
                print("\nFailed to get ticker prices, quitting")
                return
            
            print("\rWaiting... (ESC quits)\r", end="")            

        # CPU time saver
        time.sleep(0.5)
    
    print("\rDisconnecting from printer. Goodbye")
    broker.disconnect()
    printer.unload()
    
    
if __name__ == "__main__":

    # supply if defaults are empty
    while (DEFAULT_USERID == 0):
        try:
            DEFAULT_USERID = int(input("User ID (numeric):      "))
        except:
            pass
            
    while (DEFAULT_PASSWORD == ""):
        DEFAULT_PASSWORD = getpass.getpass("User password:          ")        
            
    if ((DEFAULT_ACCOUNT_TYPE != "REAL") and (DEFAULT_ACCOUNT_TYPE != "DEMO")):
        print("\r(R)eal or (D)emo acc?:  ", end="")
        while True:
            c = getch()
            if ((c == b'r') or (c == b'R')):
                DEFAULT_ACCOUNT_TYPE = "REAL"
                print("R")
                break
            elif ((c == b'd') or (c == b'D')):
                DEFAULT_ACCOUNT_TYPE = "DEMO"
                print("D")
                break                
            
    while (DEFAULT_PRINTER_NAME == ""):
        DEFAULT_PRINTER_NAME = input("Bluetooth printer name: ")
        
    main()	