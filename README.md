# HoyControl
HoyControl is a Python script that controls Hoymiles microinverters to switch off solar panles when the day-ahead electricity price becomes negative. The code provides the following features

- It checks the day-ahead prices and turns off (on) the microinverters when prices are negative (positive)
- It minimizes web traffic by checking prices only once a day and sleeping until the price sign changes 
- If an inverter fails to toggle, the code sleeps for 15 min. If all succeed it, sleeps till price sign changes
- It creates rotating file logs (weekly, 4 backups)
- It handles exceptions when the Hoymiles server rejects connection 
- It adds a price margin to the base EUR/kWh price in function `find_current_price_block(prices)`. This provides control over how negative the price should become before turning solar panels off 

The code reads a CSV file called "inverter_data.csv" that includes the Hoymiles user credentials in the following format (first line is a comment line)  
`% contact_info, username, password, DTU_id, inverter_id`  
`example@gmail.com,Hoymiles_username,Encoded_password,DTU_id,inverter_id`  

The code uses the day-ahead prices for the Netherlands. You can change this by modifying the ENTSOE_DOMAIN_NL variable. The code also expects the user to have a token that grants access to the day-ahead electricity prices on the ENTSOE website. The token should be provided in the ENTSOE_TOKEN variable. This token can be requested by creating an account on the transparency.entsoe.eu website and requesting restful API access.

For questions you can contact us at stelatron@gmail.com
