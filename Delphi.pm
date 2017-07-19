package Delphi;
use exact;

use Carp 'croak';
use Date::Parse 'str2time';
use IO::Socket::SSL;
use Mojo::DOM;
use Mojo::UserAgent;
use Readonly::Tiny 'Readonly';
use Time::HiRes 'sleep';
use Try::Tiny;
use WWW::Mechanize::PhantomJS;

Readonly my $forums_url   => 'http://forums.delphiforums.com';
Readonly my $profiles_url => 'http://profiles.delphiforums.com';

sub new ( $package, $self ) {
    for ( qw( forum username password ) ) {
        croak(qq{"$_" not defined properly}) unless ( defined $self->{$_} and length $self->{$_} );
    }

    # setup phantom mech and phantom driver
    $self->{mech}   = WWW::Mechanize::PhantomJS->new;
    $self->{driver} = $self->{mech}->driver;

    $self->{mech}->viewport_size({ width => 1100, height => 990 });
    $self->{mech}->eval_in_phantomjs(
        'this.settings.userAgent = arguments[0]',
        'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0',
    );

    # setup useragent
    $self->{ua} = Mojo::UserAgent->new;
    $self->{ua}->transactor->name('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0');
    $self->{ua}->max_redirects(5);

    return bless( $self, __PACKAGE__ );
}

sub login ($self) {
    unless ( $self->{logged_in} ) {
        # visit initial page
        $self->{mech}->get("$forums_url/$self->{forum}");

        # fill out and submit login form
        $self->{mech}->by_id( 'lgnForm_username', single => 1 )->clear;
        $self->{mech}->by_id( 'lgnForm_password', single => 1 )->clear;
        $self->{mech}->by_id( 'lgnForm_username', single => 1 )->send_keys( $self->{username} );
        $self->{mech}->by_id( 'lgnForm_password', single => 1 )->send_keys( $self->{password} );
        $self->{mech}->by_id( 'df_lgnbtn', single => 1 )->click;

        # wait for login to complete
        my $waits;
        while ( $self->{mech}->title =~ /log\s*in/i ) {
            die "Login failed after 10 seconds\n" if ( $waits++ > 10 );
            sleep 1;
        }

        $self->{logged_in} = 1;
    }

    # copy cookies from phantom driver into useragent's cookie jar in a very
    # careful (and stupid) way to "hack" the domain so all cookies will all
    # show up for the forums URL
    $self->{ua}->cookie_jar->add(
        map {
            Mojo::Cookie::Response->new(
                name   => $_->{name},
                value  => $_->{value},
                domain => 'forums.delphiforums.com',
                path   => '/',
            )
        } @{ $self->{driver}->get_all_cookies }
    );

    return $self;
}

sub most_recent_thread ($self) {
    $self->login;

    my ( $most_recent_thread, $tries );
    while ( ++$tries < 3 ) {
        # visit messages page
        $self->{mech}->get("$forums_url/$self->{forum}/messages");

        # select the nav/list frame
        $self->{driver}->switch_to_frame('LowerFrame');
        $self->{driver}->switch_to_frame('ListWin');

        # find the most recent message thread ID from links
        $most_recent_thread = Mojo::DOM->new( $self->{driver}->get_page_source )
            ->find('a')->map( attr => 'href' )
            ->grep( sub { $_ and m|/$self->{forum}/messages/| } )
            ->map( sub { m|(\d+)/\d+|; $1 } )
            ->sort( sub { $b <=> $a } )->first;

        last if ($most_recent_thread);
        sleep 1;
    }

    die "Failed to find most recent thread ID after 3 attempts\n" unless ($most_recent_thread);
    return $most_recent_thread;
}

sub msgs_dom ( $self, $current_thread = $self->most_recent_thread, $message_number = 1 ) {
    $self->login;

    sleep $self->{lag};

    my $msg = ( $current_thread =~ /\./ ) ? $current_thread : "$current_thread.$message_number";

    # visit page of first message in thread
    my @err;
    try {
        $self->{mech}->get("$forums_url/$self->{forum}/messages?msg=$msg");
    }
    catch {
        @err = @_;
    };
    return if (@err);

    # select the messages frame
    $self->{driver}->switch_to_frame('LowerFrame');
    $self->{driver}->switch_to_frame('MsgWin');

    # build a DOM object of the messages HTML
    return Mojo::DOM->new( $self->{driver}->get_page_source );
}

sub thread_data ( $self, $current_thread = $self->most_recent_thread ) {
    my ( $msgs, $msg_unsubj, $tries );

    while ( ++$tries < 3 ) {
        $msgs = $self->msgs_dom($current_thread);
        return unless ($msgs);

        my $msghead = $msgs->at('table#msgUN tr.msgCdwd td.msghead');
        return if ( $msghead and $msghead->all_text =~ /No discussions/ );

        $msg_unsubj = $msgs->at('td#msgUNsubj');

        last if ($msg_unsubj);
        sleep 1;
    }
    die "Failed to find topic summary in page after 3 attempts\n" unless ($msg_unsubj);
    $msg_unsubj->all_text =~ /(?<folder>[\w ]+)\s*\-\s*(?<topic>[\w ]*?\w)\s*\((?<views>\d+)/;

    my %metadata  = %+;
    my $total_msg = 0;
    my @messages;

    while (1) {
        push( @messages, map {
            my $msg = $_;
            $total_msg = $1 if ( not $total_msg and $msg->at('td.msgNum')->all_text =~ /\(\d+ of (\d+)\)/ );

            ( my $date = $msg->at('td.msgDate')->all_text ) =~ s/\s+$//;
            $date =~ s/-/ /g;
            $date = localtime( str2time($date) );

            $msg->at('table.df-msginner td.wintiny')->all_text =~ m|
                (?<id>\d+\.\d+)\s*
                in\s*reply\s*to\s*
                (?<in_reply_to>\d+\.\d+)
            |x;
            my %ids = %+;
            $ids{id} //= ( $current_thread =~ /\./ ) ? $current_thread : "$current_thread.1";

            my $body = $msg->at('td.msgtxt div.os-msgbody');
            return unless ($body);

            my $images = $body->find('img')->grep( sub { $_->attr('src') } )->map( sub {
                my $src = $_->attr('src');
                unless ( $src =~ m|^\w+://| ) {
                    $src = $forums_url . $_->attr('src');
                    $_->attr( 'src' => $src );
                }
                $src;
            } )->to_array;

            ( my $from = $msg->at('td.msgFname')->all_text ) =~ s/(^\s+|\s+$)//g;
            ( my $to   = $msg->at('td.msgTname')->all_text ) =~ s/(^\s+|\s+$)//g;
            $from =~ s/\s/ /g;
            $to   =~ s/\s/ /g;

            +{
                %ids,
                date        => $date,
                from        => $from,
                to          => $to,
                content     => $body->content,
                images      => $images,
                attachments => [
                    map {
                        ( my $size = $_->text ) =~ s/(^\s+|\s+$)//g;
                        my $link = $_->at('a');

                        +{
                            name => $link->at('span.text')->text,
                            href => $forums_url . $link->attr('href'),
                            size => $size,
                        };
                    } $msg->find('li.os-attachment')->each
                ],
            };
        } $msgs->find('table')->grep( sub { $_->attr('id') and $_->attr('id') =~ /^df_msg_\d+/ } )->each );

        # decide to loop if there's a "Keep Reading" button with a message ID
        my $keep_reading = $msgs->find('button.os-btn')->grep( sub {
            my $span = $_->at('span');
            $span and $span->text and $span->text =~ /Keep Reading/;
        } );
        if ( $keep_reading and $keep_reading->size ) {
            my ($next_msg_id) = $keep_reading->first->attr('onclick') =~ /\bmsg\s*=\s*\d+\.(\d+)/;
            if ($next_msg_id) {
                $msgs = $self->msgs_dom( $current_thread, $next_msg_id );
                last unless ($msgs);
                next;
            }
        }

        last;
    };

    return {
        thead_id => $current_thread,
        metadata => \%metadata,
        messages => \@messages,
    };
}

sub profile_data ( $self, $profile ) {
    $self->login;

    sleep $self->{lag};

    $self->{mech}->get("$profiles_url/$profile");

    my $dom = Mojo::DOM->new( $self->{mech}->content );

    return {
        map {
            my $text = $_;
            $text =~ s/(^\s+|\s+$)//g;
            $text =~ s/\s+/ /g;
            $text;
        } (
            (
                map { split( /:/, $_, 2 ) }
                @{ $dom->find('div.os-usermenu > ul > li')->map('text')->to_array }
            ),
            (
                map { map { $_->text } @$_ }
                grep { $_->[0] and $_->[1] }
                map { [ $_->at('label'), $_->at('span') ] }
                $dom->find('div.os-jabberform div.os-field')->each
            ),
        ),
        profile_id => $profile,
    };
}

sub save_page_as_png ( $self, $png_filename = 'page.png' ) {
    open( my $png, '>', $png_filename );
    binmode( $png, ':raw' );
    print $png $self->{mech}->content_as_png;
    close $png;

    return $self;
}

sub pull_binary ( $self, $url, $filename ) {
    $self->login;

    my $result;
    try {
        $result = $self->{ua}->get($url)->result
    };

    if ( $result and $result->code == 200 ) {
        open( my $output, '>', $filename ) or die "$!: $filename\n";
        binmode( $output, ':raw' );
        print $output $result->body;
        close $output;
    }

    return ($result) ? $result->code : 0;
}

sub get_updated_list ( $self, $days = 7 ) {
    $self->login;

    my $links = $self->{ua}
        ->get("$forums_url/n/find/results.asp?webtag=lakeamphibs&o=newest&Be=0&Af=$days")
        ->result->dom->find('a');

    my %ids = map { @$_ } @{
        $links->map( attr => 'href' )->grep( sub { $_ and /\bmsg=/ } )
            ->map( sub { /\bmsg=(\d+)\.(\d+)/; [ $1, $2 ] } )
            ->sort( sub { $b->[0] <=> $a->[0] or $b->[1] <=> $a->[1] } )
            ->map( sub { [ $_->[0], $_->[0] . '.' . $_->[1] ] } )
            ->to_array
    };

    return [ map { $ids{$_} } sort { $b <=> $a } keys %ids ];
}

1;
