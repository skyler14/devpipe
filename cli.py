"""
Command-line interface for devpipe - Interactive browser monitoring toolkit.
"""
import argparse
import asyncio
from .monitor import EventDrivenMonitor

def main():
    parser = argparse.ArgumentParser(
        description='Attach an interactive monitor to a running browser instance.',
        prog='devpipe'
    )
    
    parser.add_argument(
        '--port', '-p', 
        type=int, 
        required=True,
        help='The CDP port of the target browser instance.'
    )
    
    parser.add_argument(
        '--track-all-tabs',
        action='store_true',
        help='Automatically track all tabs and pop-ups (attaches listeners to new tabs as they open).'
    )
    
    args = parser.parse_args()

    async def run():
        monitor = EventDrivenMonitor(cdp_port=args.port, track_all_tabs=args.track_all_tabs)
        await monitor.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[devpipe] User interrupted the process. Exiting.")
    except Exception as e:
        print(f"\n[devpipe] A critical error occurred: {e}")

if __name__ == "__main__":
    main()
