# hoycontrole
Hoymiles micro-inverter controller to switch off solar panles for negative day-ahead electricity price. The code provides the following features

- It handles exceptions when the Hoymiles server rejects connection 
- It checks prices only once and sleeps until the electricity price sign changes 
- If an inverter fails it sleeps for 15 min, if all succeed it sleeps till price sign change
- It creates rotating file logs (weekly, 4 backups)
- It handles exceptions to capture Ctrl+C and other uncaught exceptions 
- It adds a price margin to the EUR/kWh price before turning solar panels off (in function "find_current_price_block(prices))

The code reads a CSV file called "inverter_data.csv" that includes the Hoymiles user credentials in the following format (first line is a comment line)
# email, username, password, DTU_id, inverter_id
example@gmail.com,Hoymiles_username,Encoded_password,DTU_id,inverter_id

The code also expects the user to have a token that grants access to the day-ahead electricity prices on the ENTSOE website. This can be arranged by creating an account on the transparency.entsoe.eu website and requesting restful API access.

