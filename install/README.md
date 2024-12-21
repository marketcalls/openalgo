# OpenAlgo Installation Guide

## Prerequisites

### System Requirements
- Ubuntu Server (22.04 LTS or later recommended)
- Minimum 2GB RAM
- Clean installation recommended

### Domain and DNS Setup (Required)
1. **Cloudflare Account Setup**
   - Create a Cloudflare account if you don't have one
   - Add your domain to Cloudflare
   - Update your domain's nameservers to Cloudflare's nameservers

2. **DNS Configuration**
   - Add an A record pointing to your server's IP address
     ```
     Type: A
     Name: yourdomain.com
     Content: YOUR_SERVER_IP
     Proxy status: Proxied
     ```
   - Add a CNAME record for www subdomain
     ```
     Type: CNAME
     Name: www
     Content: yourdomain.com
     Proxy status: Proxied
     ```

3. **SSL/TLS Configuration in Cloudflare**
   - Go to SSL/TLS section
   - Set encryption mode to "Full (strict)"

### Broker Setup (Required)
- Choose your broker from the supported list:
  ```
  fivepaisa, aliceblue, angel, dhan, fyers, icici, kotak, shoonya, upstox, zebu, zerodha
  ```
- Obtain your broker's API credentials:
  - API Key
  - API Secret

## Installation Steps

### 1. Download Installation Script
```bash
# Connect to your Ubuntu server via SSH
ssh user@your_server_ip

# Create a directory for installation
mkdir -p ~/openalgo-install
cd ~/openalgo-install

# Download the installation script
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh

# Make the script executable
chmod +x install.sh
```

### 2. Run Installation Script
```bash
# Execute the installation script
sudo ./install.sh
```

The script will interactively prompt you for:
- Your domain name (supports both root domains and subdomains)
- Broker selection
- Broker API credentials

The installation process will:
- Install required packages
- Configure Nginx with SSL
- Set up the OpenAlgo application
- Create systemd service with unique name based on domain and broker
- Generate installation logs in the logs directory

#### Multi-Domain Deployment
The installation script supports deploying multiple instances on the same server:
- Each deployment gets a unique service name (e.g., openalgo-yourdomain-broker)
- Separate configuration files and directories for each deployment
- Individual log files for each installation in the logs directory
- Independent SSL certificates for each domain
- Isolated Python virtual environments

Example of running multiple deployments:
```bash
# First deployment
sudo ./install.sh
# Enter domain: trading1.yourdomain.com
# Enter broker: fyers

# Second deployment
sudo ./install.sh
# Enter domain: trading2.yourdomain.com
# Enter broker: zerodha
```

Each deployment will:
- Have its own systemd service
- Use separate configuration files
- Store logs in unique timestamped files
- Run independently of other deployments

### 3. Verify Installation

After installation completes, verify each deployment:

1. **Check Service Status**
   ```bash
   # Example for Fyers deployment
   sudo systemctl status openalgo-fyers-yourdomain-fyers
   
   # Example for Zerodha deployment
   sudo systemctl status openalgo-zerodha-yourdomain-zerodha
   ```

2. **Verify Nginx Configuration**
   ```bash
   # Test overall Nginx configuration
   sudo nginx -t
   
   # Check specific site configurations
   ls -l /etc/nginx/sites-enabled/
   cat /etc/nginx/sites-enabled/fyers.yourdomain.com
   cat /etc/nginx/sites-enabled/zerodha.yourdomain.com
   ```

3. **Access Web Interfaces**
   Test each deployment in your web browser:
   ```
   https://fyers.yourdomain.com
   https://zerodha.yourdomain.com
   ```

4. **Check Installation Logs**
   ```bash
   # View the installation log for your deployment
   cat install/logs/install_YYYYMMDD_HHMMSS.log
   ```

## Troubleshooting

### Common Issues

1. **SSL Certificate Issues**
   ```bash
   # Check Certbot logs
   sudo journalctl -u certbot
   
   # Example: Manually run certificate installation for trading.yourdomain.com
   sudo certbot --nginx -d trading.yourdomain.com
   
   # Example: Manually run certificate installation for multiple subdomains
   sudo certbot --nginx -d fyers.yourdomain.com -d zerodha.yourdomain.com
   ```

2. **Application Not Starting**
   Example scenario: Managing multiple broker deployments
   ```bash
   # Example 1: Fyers deployment on fyers.yourdomain.com
   sudo journalctl -u openalgo-fyers-yourdomain-fyers    # View logs
   sudo systemctl restart openalgo-fyers-yourdomain-fyers # Restart service
   
   # Example 2: Zerodha deployment on zerodha.yourdomain.com
   sudo journalctl -u openalgo-zerodha-yourdomain-zerodha # View logs
   sudo systemctl restart openalgo-zerodha-yourdomain-zerodha # Restart service
   ```

3. **Nginx Issues**
   ```bash
   # Check Nginx error logs for all deployments
   sudo tail -f /var/log/nginx/error.log
   
   # Check access logs for specific domains
   sudo tail -f /var/log/nginx/fyers.yourdomain.com.access.log
   sudo tail -f /var/log/nginx/zerodha.yourdomain.com.access.log
   ```

4. **Installation Logs**
   Example: Checking installation logs for multiple deployments
   ```bash
   # List all installation logs
   ls -l install/logs/
   
   # View latest installation log
   cat install/logs/$(ls -t install/logs/ | head -1)
   
   # Example: View specific deployment logs
   cat install/logs/install_20240101_120000.log  # Fyers installation
   cat install/logs/install_20240101_143000.log  # Zerodha installation
   ```

### Managing Multiple Deployments

1. **Service Management Examples**
   ```bash
   # List all OpenAlgo services
   systemctl list-units "openalgo-*"
   
   # Example outputs:
   # openalgo-fyers-yourdomain-fyers.service    loaded active running
   # openalgo-zerodha-yourdomain-zerodha.service loaded active running
   
   # Restart specific deployment
   sudo systemctl restart openalgo-fyers-yourdomain-fyers
   
   # Check status of specific deployment
   sudo systemctl status openalgo-zerodha-yourdomain-zerodha
   ```

2. **Log Management Examples**
   ```bash
   # View real-time logs for Fyers deployment
   sudo journalctl -f -u openalgo-fyers-yourdomain-fyers
   
   # View last 100 lines of Zerodha deployment logs
   sudo journalctl -n 100 -u openalgo-zerodha-yourdomain-zerodha
   
   # View logs since last hour for specific deployment
   sudo journalctl --since "1 hour ago" -u openalgo-fyers-yourdomain-fyers
   ```

3. **Nginx Configuration Examples**
   ```bash
   # View Nginx configs for different deployments
   sudo nano /etc/nginx/sites-available/fyers.yourdomain.com
   sudo nano /etc/nginx/sites-available/zerodha.yourdomain.com
   
   # Test Nginx configuration
   sudo nginx -t
   
   # Reload Nginx after config changes
   sudo systemctl reload nginx
   ```

4. **Installation Directory Examples**
   ```bash
   # List deployment directories
   ls -l /var/python/openalgo-flask/
   
   # Example structure:
   # /var/python/openalgo-flask/fyers-yourdomain-fyers/
   # /var/python/openalgo-flask/zerodha-yourdomain-zerodha/
   
   # Check specific deployment files
   ls -l /var/python/openalgo-flask/fyers-yourdomain-fyers/
   ```

## Security Notes

1. **Firewall**
   - The installation configures UFW to allow only HTTP, HTTPS, and SSH
   - Additional ports can be opened if needed:
     ```bash
     sudo ufw allow <port_number>
     ```

2. **SSL/TLS**
   - Certificates are automatically renewed by Certbot
   - The installation configures modern SSL parameters
   - Regular updates are recommended:
     ```bash
     sudo apt update && sudo apt upgrade -y
     ```

## Post-Installation

1. Configure your broker settings in the web interface
2. Set up monitoring and alerts if needed
3. Regularly check logs for any issues
4. Keep the system updated with security patches

## Support

For issues and support:
- Check the [GitHub repository](https://github.com/marketcalls/openalgo)
- Review the logs using commands provided above
- Contact support with relevant log information

Remember to:
- Regularly backup your configuration
- Monitor system resources
- Keep the system updated
- Review security best practices
