# OpenAlgo Installation Guide

## Prerequisites

### System Requirements
- Ubuntu Server (20.04 LTS or later recommended)
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
- Your domain name
- Broker selection
- Broker API credentials

The installation process will:
- Install required packages
- Configure Nginx with SSL
- Set up the OpenAlgo application
- Create systemd service

### 3. Verify Installation

After installation completes, verify that:
1. The application is running:
   ```bash
   sudo systemctl status openalgo
   ```

2. Nginx is configured properly:
   ```bash
   sudo nginx -t
   ```

3. Access your domain in a web browser:
   ```
   https://yourdomain.com
   ```

## Troubleshooting

### Common Issues

1. **SSL Certificate Issues**
   ```bash
   # Check Certbot logs
   sudo journalctl -u certbot
   
   # Manually run certificate installation
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```

2. **Application Not Starting**
   ```bash
   # Check application logs
   sudo journalctl -u openalgo
   
   # Restart the service
   sudo systemctl restart openalgo
   ```

3. **Nginx Issues**
   ```bash
   # Check Nginx error logs
   sudo tail -f /var/log/nginx/error.log
   
   # Check Nginx access logs
   sudo tail -f /var/log/nginx/access.log
   ```

### Useful Commands

```bash
# Restart OpenAlgo
sudo systemctl restart openalgo

# View OpenAlgo logs
sudo journalctl -u openalgo

# Check OpenAlgo status
sudo systemctl status openalgo

# Restart Nginx
sudo systemctl restart nginx

# View Nginx configuration
sudo nano /etc/nginx/sites-available/yourdomain.com
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
